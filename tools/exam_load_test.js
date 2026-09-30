import http from 'k6/http';
import {check, sleep} from 'k6';
import {Counter, Trend} from 'k6/metrics';
import {SharedArray} from 'k6/data';
import {b64encode} from 'k6/encoding';
import exec from 'k6/execution';

const students = new SharedArray('load-test students', function () {
  return open(__ENV.K6_SESSION_FILE)
    .split(/\r?\n/)
    .map(function (line) { return line.trim(); })
    .filter(function (line) { return line && !line.startsWith('#'); })
    .map(function (line) {
      const separator = line.indexOf(',');
      if (separator < 0) throw new Error('Each session row must be cookie,exam_id');
      return {
        cookie: line.slice(0, separator).trim(),
        examId: line.slice(separator + 1).trim()
      };
    });
});
const frameBase64 = b64encode(open(__ENV.K6_FRAME_PATH, 'b'));
const sessionCount = parseInt(__ENV.VUS || '100', 10);

export const options = {
  vus: sessionCount,
  duration: __ENV.DURATION || '3m',
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max']
};

const questionLoadMs = new Trend('exam_question_load_ms');
const answerSaveMs = new Trend('exam_answer_save_ms');
const proctorAcceptMs = new Trend('proctoring_accept_ms');
const proctorQueueWaitMs = new Trend('proctoring_queue_wait_ms');
const proctorCvMs = new Trend('proctoring_cv_ms');
const failedFlows = new Counter('exam_load_flow_failures');
let cachedQuestionIds = null;

function encodeForm(fields) {
  return Object.keys(fields).map(function (key) {
    return encodeURIComponent(key) + '=' + encodeURIComponent(fields[key]);
  }).join('&');
}

function uuidV4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (char) {
    const random = Math.random() * 16 | 0;
    return (char === 'x' ? random : (random & 0x3 | 0x8)).toString(16);
  });
}

function headers(student) {
  return {
    Cookie: student.cookie,
    'Content-Type': 'application/x-www-form-urlencoded'
  };
}

function requestQuestions(student) {
  const response = http.post(
    __ENV.BASE_URL + '/give-test/' + encodeURIComponent(student.examId),
    encodeForm({flag: 'start'}),
    {headers: headers(student), tags: {stage: 'question_load'}}
  );
  questionLoadMs.add(response.timings.duration);
  const valid = check(response, {
    'question preload succeeds': function (res) {
      if (res.status !== 200) return false;
      const body = res.json();
      return Array.isArray(body.ids) && body.ids.length > 0 && body.questions;
    }
  });
  if (!valid) {
    failedFlows.add(1, {stage: 'question_load'});
    return null;
  }
  return response.json().ids;
}

function saveAnswer(student, questionId) {
  const response = http.post(
    __ENV.BASE_URL + '/give-test/' + encodeURIComponent(student.examId),
    encodeForm({flag: 'mark', qid: questionId, ans: 'a'}),
    {headers: headers(student), tags: {stage: 'answer_save'}}
  );
  answerSaveMs.add(response.timings.duration);
  if (!check(response, {
    'answer save succeeds': function (res) {
      return res.status === 200 && res.json().status === 'success';
    }
  })) {
    failedFlows.add(1, {stage: 'answer_save'});
  }
}

function submitFrame(student) {
  const snapshotId = uuidV4();
  const payload = encodeForm({
    'data[imgData]': frameBase64,
    'data[testid]': student.examId,
    'data[voice_db]': '0',
    'data[snapshot_id]': snapshotId
  });
  let accepted;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    accepted = http.post(__ENV.BASE_URL + '/video_feed', payload, {
      headers: headers(student),
      tags: {stage: 'proctoring_accept'}
    });
    proctorAcceptMs.add(accepted.timings.duration);
    if (accepted.status === 429 || accepted.status === 503) {
      sleep(1);
      continue;
    }
    break;
  }
  if (!accepted || accepted.status !== 202) {
    failedFlows.add(1, {stage: 'proctoring_accept'});
    return;
  }

  const jobId = accepted.json().job_id;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const result = http.get(
      __ENV.BASE_URL + '/proctoring_status/' + encodeURIComponent(jobId)
        + '?testid=' + encodeURIComponent(student.examId),
      {headers: {Cookie: student.cookie}, tags: {stage: 'proctoring_result'}}
    );
    if (result.status === 202 || result.status === 503) {
      sleep(0.5);
      continue;
    }
    if (result.status !== 200 || result.json().status !== 'success') {
      failedFlows.add(1, {stage: 'proctoring_result'});
      return;
    }
    const body = result.json();
    proctorQueueWaitMs.add(body.queue_wait_ms);
    proctorCvMs.add(body.cv_duration_ms);
    return;
  }
  failedFlows.add(1, {stage: 'proctoring_timeout'});
}

export default function () {
  if (students.length < sessionCount) {
    throw new Error('K6_SESSION_FILE must contain at least one unique student row per VU');
  }
  const student = students[exec.vu.idInTest - 1];
  if (!student.cookie || !student.examId) {
    throw new Error('Session cookie and exam id are required for each VU');
  }

  if (!cachedQuestionIds) {
    cachedQuestionIds = requestQuestions(student);
    if (!cachedQuestionIds) {
      sleep(1);
      return;
    }
  }
  saveAnswer(student, cachedQuestionIds[__ITER % cachedQuestionIds.length]);
  submitFrame(student);
  sleep(2);
}
