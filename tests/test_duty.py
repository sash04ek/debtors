"""Госпошлина по ст. 333.19 НК РФ: python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import court  # noqa: E402
import duty  # noqa: E402
import orgs  # noqa: E402
import owners  # noqa: E402
from docx import Document  # noqa: E402


class DutyScaleTest(unittest.TestCase):
    def test_known_points_for_court_order(self):
        for price, want in ((50_000, 2_000), (100_000, 2_000), (200_000, 3_500), (300_000, 5_000), (500_000, 7_500),
                            (1_000_000, 12_500), (100_000_000, 157_000)):
            self.assertEqual(duty.court_order_duty(price), want, price)

    def test_scale_is_continuous_at_thresholds(self):
        """На границах строк шкалы значение совпадает: база следующей строки = пошлина на пороге предыдущей."""
        for prev, nxt in zip(duty.DEFAULT_SCALE, duty.DEFAULT_SCALE[1:]):
            edge = prev["up_to"]
            self.assertAlmostEqual(float(duty.claim_duty(edge)), nxt["base"] + nxt["rate"] * (edge - nxt["over"]) / 100, places=2)

    def test_cap(self):
        self.assertEqual(float(duty.claim_duty(1_000_000_000)), 900_000)
        self.assertEqual(duty.court_order_duty(1_000_000_000), 450_000)

    def test_kopecks_and_share(self):
        self.assertEqual(duty.court_order_duty(177_348.10), 3_160.22)
        self.assertEqual(duty.court_order_duty(177_348.10, share=100), 6_320.44)

    def test_custom_scale(self):
        scale = [{"up_to": 10_000, "base": 400, "rate": 0, "over": 0}, {"up_to": None, "base": 400, "rate": 5, "over": 10_000}]
        self.assertEqual(float(duty.claim_duty(30_000, scale)), 1_400)

    def test_explain_mentions_result(self):
        self.assertIn("3 160.22", duty.explain(177_348.10))


class ApplicationDutyTest(unittest.TestCase):
    def _text(self, card, duty_value):
        org = orgs.Organization(name="О", match="О", duty_default="200", city="г. Таганрог", region="Ростовская область")
        case = court.Case(owners.Owner(fio="Иванов Иван Иванович"), [owners.Owner(fio="Иванов Иван Иванович")], 1000.0, None)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "z.docx"
            court.build_court_application(org, card, case, path=p, duty=duty_value)
            return "\n".join(par.text for par in Document(p).paragraphs)

    def test_priority_card_over_calc_over_org_default(self):
        base = dict(address="ул. Т, д. 1", flat="5")
        self.assertIn("3 160,22", self._text(owners.Card(**base), 3160.22).replace(" ", " "))         # расчёт
        self.assertIn("999", self._text(owners.Card(duty="999", **base), 3160.22))                           # карточка главнее
        self.assertIn("200", self._text(owners.Card(**base), None))                                          # значение организации


if __name__ == "__main__":
    unittest.main()
