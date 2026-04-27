import numpy as np
import nltk as nlp

class SubjectiveTest:

    def __init__(self, filepath, noOfQues):

        self.question_pattern = [
            "Explain in detail ",
            "Define ",
            "Write a short note on ",
            "What do you mean by "
        ]
        self.grammar = r"""
            CHUNK: {<NN>+<IN|DT>*<NN>+}
            {<NN>+<IN|DT>*<NNP>+}
            {<NNP>+<NNS>*}
        """
        self.summary = filepath
        self.noOfQues = noOfQues
    
    @staticmethod
    def word_tokenizer(sequence):
        word_tokens = list()
        for sent in nlp.sent_tokenize(sequence):
            for w in nlp.word_tokenize(sent):
                word_tokens.append(w)
        return word_tokens
    
    def generate_test(self):
        sentences = nlp.sent_tokenize(self.summary)
        cp = nlp.RegexpParser(self.grammar)
        question_answer_dict = dict()
        for sentence in sentences:
            tagged_words = nlp.pos_tag(nlp.word_tokenize(sentence))
            tree = cp.parse(tagged_words)
            for subtree in tree.subtrees():
                if subtree.label() == "CHUNK":
                    temp = ""
                    for sub in subtree:
                        temp += sub[0]
                        temp += " "
                    temp = temp.strip()
                    temp = temp.upper()
                    if temp not in question_answer_dict:
                        if len(nlp.word_tokenize(sentence)) > 20:
                            question_answer_dict[temp] = sentence
                    else:
                        question_answer_dict[temp] += sentence

        keyword_list = list(question_answer_dict.keys())

        if not keyword_list:
            return [], []

        # Build candidate pool
        question_answer = list()
        for _ in range(int(self.noOfQues)):
            rand_num = np.random.randint(0, len(keyword_list))
            selected_key = keyword_list[rand_num]
            answer = question_answer_dict[selected_key]
            rand_num %= 4
            question = self.question_pattern[rand_num] + selected_key + "."
            question_answer.append({"Question": question, "Answer": answer})

        # De-duplicate, pick up to noOfQues without infinite loop
        que = []
        ans = []
        seen = set()
        indices = list(range(len(question_answer)))
        np.random.shuffle(indices)
        for idx in indices:
            if len(que) >= int(self.noOfQues):
                break
            q_text = question_answer[idx]["Question"]
            if q_text not in seen:
                seen.add(q_text)
                que.append(q_text)
                ans.append(question_answer[idx]["Answer"])
        return que, ans