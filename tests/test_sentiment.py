import unittest

from engine import sentiment


def item(title, age=60, relevant=True, source="X"):
    return {"title": title, "age_min": age, "relevant": relevant, "source": source}


class TitleTests(unittest.TestCase):
    def test_positive_negative_and_empty(self):
        self.assertGreater(sentiment.score_title("Infosys profit jumps, beats estimates")[0], 0.6)
        self.assertLess(sentiment.score_title("Company shares plunge after profit falls and rating downgrade")[0], -0.6)
        self.assertEqual(sentiment.score_title("Annual general meeting on Friday")[0], 0.0)
        self.assertEqual(sentiment.score_title("")[0], 0.0)

    def test_negation_turns_the_meaning_round(self):
        self.assertGreater(sentiment.score_title("Company denies fraud allegations")[0], 0)
        self.assertLess(sentiment.score_title("Company reports fraud")[0], 0)
        self.assertLess(sentiment.score_title("Firm fails to beat estimates")[0], sentiment.score_title("Firm beats estimates")[0])

    def test_a_question_reports_nothing(self):
        self.assertLess(abs(sentiment.score_title("Will the stock surge?")[0]), abs(sentiment.score_title("The stock surges")[0]))

    def test_phrases_are_read_before_single_words(self):
        value, words = sentiment.score_title("Record profit for the quarter")
        self.assertIn("record profit", words)
        self.assertGreater(value, 0.5)


class FallingAwayFromRecordsTests(unittest.TestCase):
    def test_a_retreat_from_a_record_is_not_positive_and_a_record_is_still_positive(self):
        from engine import sentiment as s
        self.assertLess(s.score_title("HDFC Bank shares, Bank Nifty retreat sharply from record highs")[0], 0)
        self.assertLess(s.score_title("Nifty slips from record high")[0], 0)
        self.assertGreater(s.score_title("Sensex hits record high")[0], 0)
        self.assertGreater(s.score_title("Company posts record profit")[0], 0)
