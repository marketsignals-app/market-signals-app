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


class ToneTests(unittest.TestCase):
    def test_nothing_to_read_gives_none(self):
        self.assertIsNone(sentiment.tone([]))
        self.assertIsNone(sentiment.tone([item("Surges", relevant=False)]))
        self.assertIsNone(sentiment.tone([item("Surges", age=100 * 60)]))
        self.assertIsNone(sentiment.component(sentiment.tone([item("Meeting scheduled")])))

    def test_one_headline_cannot_move_the_tone_far(self):
        one = sentiment.tone([item("Stock soars on record profit")])
        many = sentiment.tone([item(t) for t in ("Stock soars on record profit", "Company wins big order", "Brokerage upgrade lifts shares", "Profit jumps in quarter",
                                                 "Shares rally on approval", "Firm secures new contract")])
        self.assertLess(one["score"], many["score"])
        self.assertLess(one["score"], 0.5)
        self.assertEqual((one["confidence"], many["confidence"]), ("low", "higher"))

    def test_recent_headlines_count_more_and_duplicates_once(self):
        fresh_good = [item("Company wins big order", age=30), item("Company wins big order", age=40)]
        self.assertEqual(sentiment.tone(fresh_good)["n"], 1)
        mixed = sentiment.tone([item("Shares plunge on profit warning", age=70 * 60), item("Company wins order, stock rallies", age=20)])
        self.assertGreater(mixed["score"], 0)

    def test_component_text_says_it_is_word_based_and_low_weight(self):
        value, text = sentiment.component(sentiment.tone([item("Stock rallies on upgrade"), item("Profit jumps")]))
        self.assertGreater(value, 0)
        self.assertIn("word-based, low weight", text)
        self.assertIn("leaning positive", text)


class FallingAwayFromRecordsTests(unittest.TestCase):
    def test_a_retreat_from_a_record_is_not_positive_and_a_record_is_still_positive(self):
        from engine import sentiment as s
        self.assertLess(s.score_title("HDFC Bank shares, Bank Nifty retreat sharply from record highs")[0], 0)
        self.assertLess(s.score_title("Nifty slips from record high")[0], 0)
        self.assertGreater(s.score_title("Sensex hits record high")[0], 0)
        self.assertGreater(s.score_title("Company posts record profit")[0], 0)
