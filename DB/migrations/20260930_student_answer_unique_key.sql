ALTER TABLE `students`
  ADD UNIQUE KEY `uniq_student_exam_answer` (`test_id`, `qid`, `email`, `uid`);

ALTER TABLE `questions`
  ADD KEY `idx_questions_test_id` (`test_id`);

ALTER TABLE `studenttestinfo`
  ADD KEY `idx_studenttestinfo_exam_student` (`test_id`, `email`, `uid`, `completed`);
