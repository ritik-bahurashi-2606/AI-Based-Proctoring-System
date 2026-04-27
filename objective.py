import re
import nltk
import numpy as np
from nltk.corpus import wordnet as wn

class ObjectiveTest:

    def __init__(self, filepath, noOfQues):
        
        self.summary = filepath
        self.noOfQues = noOfQues

    def get_trivial_sentences(self):
        sentences = nltk.sent_tokenize(self.summary)
        trivial_sentences = list()
        for sent in sentences:
            trivial = self.identify_trivial_sentences(sent)
            if trivial:
                trivial_sentences.append(trivial)
            else:
                continue
        return trivial_sentences

    def identify_trivial_sentences(self, sentence):
        tags = nltk.pos_tag(nltk.word_tokenize(sentence))
        if tags[0][1] == "RB" or len(nltk.word_tokenize(sentence)) < 4:
            return None
        
        noun_phrases = list()
        grammer = r"""
            CHUNK: {<NN>+<IN|DT>*<NN>+}
                {<NN>+<IN|DT>*<NNP>+}
                {<NNP>+<NNS>*}
            """
        chunker = nltk.RegexpParser(grammer)
        tokens = nltk.word_tokenize(sentence)
        pos_tokens = nltk.tag.pos_tag(tokens)
        tree = chunker.parse(pos_tokens)

        for subtree in tree.subtrees():
            if subtree.label() == "CHUNK":
                temp = ""
                for sub in subtree:
                    temp += sub[0]
                    temp += " "
                temp = temp.strip()
                noun_phrases.append(temp)
        
        replace_nouns = []
        for word, _ in tags:
            for phrase in noun_phrases:
                if phrase[0] == '\'':
                    break
                if word in phrase:
                    [replace_nouns.append(phrase_word) for phrase_word in phrase.split()[-2:]]
                    break
            if len(replace_nouns) == 0:
                replace_nouns.append(word)
            break
        
        if len(replace_nouns) == 0:
            return None
        
        val = 99
        for i in replace_nouns:
            if len(i) < val:
                val = len(i)
            else:
                continue
        
        trivial = {
            "Answer": " ".join(replace_nouns),
            "Key": val
        }

        if len(replace_nouns) == 1:
            trivial["Similar"] = self.answer_options(replace_nouns[0])
        else:
            trivial["Similar"] = []
        
        replace_phrase = " ".join(replace_nouns)
        blanks_phrase = ("__________" * len(replace_nouns)).strip()
        expression = re.compile(re.escape(replace_phrase), re.IGNORECASE)
        sentence = expression.sub(blanks_phrase, str(sentence), count=1)
        trivial["Question"] = sentence
        return trivial

    @staticmethod
    def answer_options(word):
        synsets = wn.synsets(word, pos="n")

        if len(synsets) == 0:
            return []
        else:
            synset = synsets[0]
        
        hypernym = synset.hypernyms()[0]
        hyponyms = hypernym.hyponyms()
        similar_words = []
        for hyponym in hyponyms:
            similar_word = hyponym.lemmas()[0].name().replace("_", " ")
            if similar_word != word:
                similar_words.append(similar_word)
            if len(similar_words) == 8:
                break
        return similar_words

    def generate_test(self):
        trivial_pair = self.get_trivial_sentences()
        # Keep all valid trivial sentences as candidates (the old filter
        # "Key > noOfQues" wrongly used the requested count as a word-length
        # threshold, which removed almost everything when noOfQues > 3).
        question_answer = [q for q in trivial_pair if q]

        if not question_answer:
            return [], []

        # De-duplicate and collect up to noOfQues questions
        question = []
        answer = []
        seen = set()
        # Shuffle indices so we pick randomly without replacement
        indices = list(range(len(question_answer)))
        np.random.shuffle(indices)
        for idx in indices:
            if len(question) >= int(self.noOfQues):
                break
            q_text = question_answer[idx]["Question"]
            if q_text not in seen:
                seen.add(q_text)
                question.append(q_text)
                answer.append(question_answer[idx]["Answer"])
        return question, answer