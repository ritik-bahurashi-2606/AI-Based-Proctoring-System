var nos = [];
var curr = 0;
var data = {};
var examUrl = window.location.pathname;
var timerInterval = null;
var timeSyncInterval = null;
var submissionInProgress = false;
var answerSaveQueue = Promise.resolve();
var savedAnswers = {};
var queuedAnswers = {};
var questionsById = {};
var questionLoadError = null;
const NOT_MARKED=0;
const MARKED=1;
const BOOKMARKED=2;
const MARKED_BOOKMARKED=3;
const SUBMITTED = 4;
const SUBMITTED_BOOKMARKED = 5;

function mySnackBar() {
    var x = document.getElementById("snackbar");
    x.className = "show";
    setTimeout(function(){ x.className = x.className.replace("show", ""); }, 10000);
  }

// NOTE: Tab-switch and blur events are handled by proctoring_common.js
// The onfocus handler was incorrectly logging window events — removed.

function startExamProctoring() {
    if (typeof window.startStreaming === 'function') {
        window.startStreaming();
    }
    if (typeof window.captureSnapshot === 'function') {
        window.captureSnapshot();
    }
}

$(document).ready( function() {
    var url = window.location.href;
    $('.question').remove();
    if (url.includes('/give-test/')) {
        $('#que').text('Loading exam questions...');
        $.ajax({
            type:"POST",
            url: examUrl,
            dataType:"json",
            data : {flag: 'start'},
            success: function(temp) {
                nos = (temp && temp.ids) || [];
                questionsById = (temp && temp.questions) || {};
                if (!nos.length || nos.some(function(qid) { return !questionsById[String(qid)]; })) {
                    questionLoadError = new Error('The exam questions could not be loaded.');
                    console.error(questionLoadError);
                    $('#que').text('Exam questions could not be loaded. Please refresh the exam page.');
                    return;
                }
                make_array();
                display_ques(1);
                ques_grid();
            },
            error: function(error) {
                questionLoadError = error;
                console.error('Could not load exam questions:', error);
                $('#que').text('Exam questions could not be loaded. Please refresh the exam page.');
            }
        });
    }
    var time = parseInt($('#time').text()), display = $('#time');
    startTimer(time, display);
    sendTime();
    flag_time = true;

})

var unmark_all = function() {
    $('#options td').each(function(i) 
    {
        $(this).css("background-color",'rgba(0, 0, 0, 0)');
    });
}

var display_ques = function(move) {
    unmark_all();
    if (!nos.length || !data[curr+1]) return;
    var temp = questionsById[String(nos[curr])];
    if (!temp) {
        questionLoadError = new Error('Question ' + (curr + 1) + ' is missing from the loaded exam.');
        console.error(questionLoadError);
        return;
    }
    $('#que').text(temp.q);
    $('#a').text('𝐀.  '+temp.a);
    $('#b').text('𝐁.  '+temp.b);
    $('#c').text('𝐂.  '+temp.c);
    $('#d').text('𝐃.  '+temp.d);
    $('#queid').text('Question No. '+ move);
    $('#mark').text('Marks: '+temp.marks);
    if(data[curr+1].marked != null)
       $('#' + data[curr+1].marked).css("background-color",'rgba(0, 255, 0, 0.6)');
}
var flag_time = true;
function startTimer(duration, display) {
    var timer = duration,hours, minutes, seconds;
    
    timerInterval = setInterval(function () {
        hours = parseInt(timer / 3600 ,10);
        minutes = parseInt((timer%3600) / 60, 10);
        seconds = parseInt(timer % 60, 10);
        hours = hours < 10 ? "0" + hours : hours;
        minutes = minutes < 10 ? "0" + minutes : minutes;
        seconds = seconds < 10 ? "0" + seconds : seconds;

        display.text(hours + ":" + minutes + ":" + seconds);

        if (--timer < 0) {
            finish_test();
            clearInterval(timerInterval);
            flag_time = false;
        }
    }, 1000);
}

function finish_test() {
    if (questionLoadError || !nos.length) {
        var loadMessage = 'Exam questions are not ready yet. Please wait and try again.';
        if (window.Swal) {
            Swal.fire('Exam not ready', loadMessage, 'error');
        } else {
            alert(loadMessage);
        }
        return;
    }
    if (submissionInProgress) return;
    submissionInProgress = true;
    save_current_answer(false);
    $('#msg').addClass('alert-info');
    $('#msg').append("Test submitted successfully");
    flag_time = false;
    if (timerInterval) clearInterval(timerInterval);
    if (timeSyncInterval) clearInterval(timeSyncInterval);
    var audioUploadComplete = typeof window.stopStreaming === 'function'
        ? window.stopStreaming()
        : Promise.resolve();

    // Collect all marked answers across all questions
    var all_answers = {};
    for (var i = 1; i <= nos.length; i++) {
        if (data[i]) {
            all_answers[nos[i-1]] = data[i].marked || '';
        }
    }

    var submitAnswers = function () {
        $.ajax({
            type: "POST",
            dataType: "json",
            url: examUrl,
            data: {
                flag: 'completed',
                answers: JSON.stringify(all_answers)
            },
            success: function(resp) {
                if (!resp || resp.status !== 'success') {
                    submissionInProgress = false;
                    var message = (resp && resp.message) || 'The exam could not be submitted. Please try again.';
                    console.error('Finish test failed:', message);
                    if (window.Swal) {
                        Swal.fire('Submit failed', message, 'error');
                    } else {
                        alert(message);
                    }
                    return;
                }
                if (window.SecureExam) window.SecureExam.end();
                if (resp && resp.redirect_url) {
                    window.location.replace(resp.redirect_url);
                } else {
                    window.location.replace('/student_index');
                }
            },
            error: function(error) {
                submissionInProgress = false;
                console.error("Finish test failed:", error);
                var message = error.responseJSON && error.responseJSON.message
                    ? error.responseJSON.message
                    : 'Please check your connection and try again.';
                if (window.Swal) {
                    Swal.fire('Submit failed', message, 'error');
                } else {
                    alert(message);
                }
            }
        });
    };
    Promise.resolve(audioUploadComplete).catch(function(error) {
        console.error('Audio evidence upload did not finish before exam submission:', error);
        if (window.Swal) {
            Swal.fire({
                toast: true,
                position: 'top-end',
                icon: 'warning',
                title: 'Audio evidence could not be saved.',
                showConfirmButton: false,
                timer: 5000
            });
        } else {
            console.warn('Audio evidence could not be saved.');
        }
    }).then(function() {
        return answerSaveQueue;
    }).then(submitAnswers);
}

function sendTime() {
    timeSyncInterval = setInterval(function() {
        if(flag_time == false){
            clearInterval(timeSyncInterval);
        }
        var time = $('#time').text();
        var [hh,mm,ss] = time.split(':');
        hh = parseInt(hh);
        mm = parseInt(mm);
        ss = parseInt(ss);
        var seconds = hh*3600 + mm*60 + ss;
        $.ajax({
            type: 'POST',
            dataType: "json",
            url: examUrl,
            data: {flag:'time', time: seconds},
        });
        if(flag_time == false){
            clearInterval(timeSyncInterval);
        }
    }, 5000);
}

$(document).on('click', '#next', function(e){
    e.preventDefault();
    if (!nos.length) return;
    save_current_answer(false);
    if (curr >= nos.length - 1) return;
    curr += 1;
    display_ques(curr+1);
    
});

$(document).on('click', '#prev', function(e){
    e.preventDefault();
    if (!nos.length || curr <= 0) return;
    save_current_answer(false);
    curr -= 1;
    display_ques(curr+1);
    
});

function save_current_answer(markSubmitted) {
    if(flag_time == false){
        return false;
    }
    var answerData = data[curr+1];
    if (!answerData) return false;
    var qid = String(nos[curr]);
    var answer = answerData.marked;
    if (answer !== null && answer !== undefined) {
        if (answerData.status === BOOKMARKED || answerData.status === SUBMITTED_BOOKMARKED) {
            answerData.status = SUBMITTED_BOOKMARKED;
        } else if (markSubmitted || answerData.status === MARKED) {
            answerData.status = SUBMITTED;
        }
    } else if (!Object.prototype.hasOwnProperty.call(queuedAnswers, qid)) {
        return false;
    }
    updateQuestionGridItem(curr);
    if (Object.prototype.hasOwnProperty.call(queuedAnswers, qid) && queuedAnswers[qid] === answer) return true;
    queuedAnswers[qid] = answer;

    var saveRequest = answerSaveQueue.then(function() {
        return $.ajax({
            type: 'POST',
            dataType: 'json',
            url: examUrl,
            data: {flag: 'mark', qid: qid, ans: answer || ''}
        });
    }).then(function(response) {
        if (!response || response.status !== 'success') {
            throw new Error((response && response.message) || 'The answer could not be saved.');
        }
        if (answer === null || answer === undefined) {
            delete savedAnswers[qid];
        } else {
            savedAnswers[qid] = answer;
        }
    }).catch(function(error) {
        if (queuedAnswers[qid] === answer) delete queuedAnswers[qid];
        throw error;
    });
    answerSaveQueue = saveRequest.catch(function(error) {
        console.error('Answer save failed for question ' + qid + ':', error);
    });
    return true;
}

$('#submit').on('click', function(e){
    e.preventDefault();
    if (save_current_answer(true) && curr < nos.length - 1) {
        curr += 1;
        display_ques(curr+1);
    }
});

$('#bookmark').on('click', function(e){
    var status = data[curr+1].status;
    if( status == MARKED)
    {
        data[curr+1].status = MARKED_BOOKMARKED;
    }
    else if(status == SUBMITTED)
    {
        data[curr+1].status = SUBMITTED_BOOKMARKED;
    }
    else
    {
        data[curr+1].status = BOOKMARKED;
    }
    updateQuestionGridItem(curr);
});



$('#options').on('click', 'td', function(){
    if ($(this).css("background-color") != 'rgba(0, 255, 0, 0.6)') {
        var clicked = $(this).attr('id');
        var que = $('#queid').attr('id');
        unmark_all();
        $(this).css("background-color",'rgba(0, 255, 0, 0.6)');
        if (data[curr+1].status !== SUBMITTED && data[curr+1].status !== SUBMITTED_BOOKMARKED) {
            data[curr+1].status = MARKED;
        }
        data[curr+1].marked = $(this).attr('id');
        save_current_answer(false);
    }
    else {
        var previousAnswer = data[curr+1].marked;
        $(this).css("background-color",'rgba(0, 0, 0, 0)');
        data[curr+1].status = NOT_MARKED;
        data[curr+1].marked = null;
        if (previousAnswer) save_current_answer(false);
    }
});

var submit_overlay_display = true;
$('#finish').on("click", function(e) {
     funSubmitExam();

});

var marked = function() {
    var count = 0;
    for(var i=1;i<=nos.length;i++){
        if(data[i] && data[i].marked){
            count++;
        } 
    }
    return count;
}

var ques_grid = function() {
    document.getElementById("overlay").style.display = "block";
    for(var i=1;i<=nos.length;i++) {
        var color = questionStatusColor(data[i].status);
        j = i<10 ? "0" + i: i
        $('#question-list').append('<div class="col-sm-2"><button class="btn btn-primary" style="background-color:' + color + '; color:white;"><div class="question" style="background-color:' + color + '; color:white;">' + j + '</div></div></div>');
    }
    $('.question').click(function() {
        save_current_answer(false);
        var id = parseInt($(this).text());
        curr = id-1;
        display_ques(curr+1);
    });
}

function questionStatusColor(status) {
    if (status === NOT_MARKED) return '#1976D2';
    if (status === SUBMITTED) return '#42ed62';
    if (status === BOOKMARKED || status === SUBMITTED_BOOKMARKED) return '#e6ed7b';
    return '#f44336';
}

function updateQuestionGridItem(questionIndex) {
    var answerData = data[questionIndex + 1];
    var question = $('#question-list .question').eq(questionIndex);
    if (!answerData || !question.length) return;
    var color = questionStatusColor(answerData.status);
    question.css('background-color', color);
    question.closest('button').css('background-color', color);
}

var make_array = function() {
    for(var i=0; i<nos.length; i++){
        data[i+1] = {marked : null, status: NOT_MARKED}; 
    }
    var txt = document.createElement('textarea');
    txt.innerHTML = answers;
    answers = txt.value;
    try {
        answers = JSON.parse(answers || '{}');
    } catch (err) {
        console.warn('Could not parse saved answers:', err);
        answers = {};
    }
    for(var key in answers) {
        var questionIndex = nos.map(String).indexOf(String(key));
        if (questionIndex >= 0 && data[questionIndex+1]) {
            data[questionIndex+1].marked = answers[key];
            data[questionIndex+1].status = SUBMITTED;
            savedAnswers[String(key)] = answers[key];
            queuedAnswers[String(key)] = answers[key];
        }
    }
}

function funSubmitExam()
{
    var count = marked();
    var remaining = nos.length - count;
  Swal.fire({
  title: '<strong>FINISH EXAM</strong>',
  icon: 'warning',
  html:
    '<table><tr><td>TOTAL QUESTIONS:</td><td>'+nos.length+'</td></tr><tr><td>ATTEMPTED:</td><td>'+count+'</td></tr><tr><td>REMAINING:</td><td>'+remaining+'</td></tr></table>' ,
  showCloseButton: false,
  showCancelButton: true,
  focusConfirm: true,
  confirmButtonText:
    'OK, FINISH MY EXAM!',
  confirmButtonAriaLabel: 'We are abide by rules!'
}).then((result) => {
  if (result.isConfirmed) {
    finish_test();
  }
})
}

  window.addEventListener('selectstart', function(e){ e.preventDefault(); });
  $(document).ready(function () {
      $('body').bind('select cut copy paste', function (e) {
          e.preventDefault();
      });
      
      $("body").on("contextmenu",function(e){
          return false;
      });
  });

  document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key == 'p') {
  alert('This section is not allowed to print or export to PDF');
  e.cancelBubble = true;
  e.preventDefault();
  e.stopImmediatePropagation();
  }
  });
