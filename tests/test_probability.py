import unittest
from models.probability import distribution_probabilities as masses, price_metrics


class ProbabilityTests(unittest.TestCase):
    def test_integer_push(self):
        self.assertEqual(masses([0, 3, 7], [.25, .25, .5], 3), (.5, .25, .25))

    def test_half_point_no_push(self):
        self.assertEqual(masses([0, 3, 7], [.25, .25, .5], 3.5), (.5, 0, .5))

    def test_push_ev_not_binary_complement(self):
        result = price_metrics(.5, .25, .25, -110)
        self.assertAlmostEqual(result['ev_per_unit_risk'], .5 * 100 / 110 - .25)
        self.assertAlmostEqual(result['win_conditional_nonpush'], 2 / 3)
        self.assertAlmostEqual(result['fair_american_odds'], -200)
        self.assertEqual(result['approved_risk'], 0)

    def test_both_selections(self):
        w, p, l = masses([40, 41, 42], [.2, .3, .5], 41)
        self.assertAlmostEqual(price_metrics(l, p, w, 150)['ev_per_unit_risk'], -.2)

    def test_all_push(self):
        result = price_metrics(0, 1, 0, 100)
        self.assertEqual(result['ev_per_unit_risk'], 0)
        self.assertIsNone(result['win_conditional_nonpush'])
        self.assertIsNone(result['fair_american_odds'])

    def test_plus_and_minus_odds(self):
        self.assertAlmostEqual(price_metrics(.6, 0, .4, 150)['ev_per_unit_risk'], .5)
        self.assertAlmostEqual(price_metrics(.6, 0, .4, -150)['ev_per_unit_risk'], 0)
        self.assertEqual(price_metrics(.4, .2, .4, 100)['fair_american_odds'], 100)

    def test_reject_invalid_distributions(self):
        for outcomes, weights, line in [([], [], 3), ([1], [.2], 3),
                ([1.5], [1], 3), ([1], [float('nan')], 3),
                ([1], [1], float('inf')), ([1, 2], [-1, 2], 3), ([1], [], 3)]:
            with self.subTest(outcomes=outcomes, weights=weights, line=line):
                with self.assertRaises(ValueError):
                    masses(outcomes, weights, line)

    def test_reject_invalid_prices_and_masses(self):
        for args in [(.5, 0, .6, -110), (-.1, .5, .6, 100),
                     (.5, 0, .5, 0), (.5, 0, .5, 90),
                     (.5, 0, .5, float('nan'))]:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    price_metrics(*args)


if __name__ == '__main__':
    unittest.main()
