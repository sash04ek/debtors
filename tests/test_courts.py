"""Список судебных участков: python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import courts as C  # noqa: E402

# фрагмент реального ответа sudrf.ru (JavaScript с записями участков)
SAMPLE = """
			if (typeof balloons_user['61MS0203'] == 'undefined'){
				balloons_user['61MS0203']= new Array();
			}
			balloons_user['61MS0203'][balloons_user['61MS0203'].length]={type:'mir',name:'Судебный участок № 10 Таганрогского судебного района Ростовской области',adress:'347900, Ростовская область, г. Таганрог, ул. Большая Бульварная, д. 8-3',coord:[47.2,38.9]};
			balloons_user['61MS0194'][balloons_user['61MS0194'].length]={type:'mir',name:'Судебный участок № 1 Таганрогского судебного района Ростовской области',adress:'347900, Ростовская область, г. Таганрог, ул. Большая Бульварная, д. 8-3',coord:[47.2,38.9]};
			balloons_user['61MS0001'][balloons_user['61MS0001'].length]={type:'mir',name:'Судебный участок № 1 Ворошиловского судебного района г. Ростова-на-Дону',adress:'344002, г. Ростов-на-Дону, ул. Пушкинская, д. 1',coord:[47.2,39.7]};
			balloons_user['30MS0001'][balloons_user['30MS0001'].length]={type:'mir',name:'Судебный участок № 1 Кировского района г. Астрахани',adress:'414040, г. Астрахань, ул. Космонавтов, д. 42',coord:[46.3,48.0]};
			balloons_user['61MS0203'][balloons_user['61MS0203'].length]={type:'mir',name:'дубль',adress:'x',coord:[1,1]};
"""


class CourtsTest(unittest.TestCase):
    def setUp(self):
        self.all = C.parse(SAMPLE)

    def test_parse_and_dedupe(self):
        self.assertEqual([c.code for c in self.all], ["61MS0203", "61MS0194", "61MS0001", "30MS0001"])
        self.assertEqual(self.all[0].address, "347900, Ростовская область, г. Таганрог, ул. Большая Бульварная, д. 8-3")

    def test_download_filters_regions_and_sorts(self):
        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return SAMPLE.encode("cp1251")
        got = C.download("61", urlopen=lambda url: R())
        self.assertEqual([c.code for c in got], ["61MS0001", "61MS0194", "61MS0203"])   # только 61, по названию и номеру
        self.assertEqual(len(C.download("61, 30", urlopen=lambda url: R())), 4)
        with self.assertRaises(C.DownloadError):
            C.download("99", urlopen=lambda url: R())

    def test_search_is_forgiving_and_numbers_match_exactly(self):
        self.assertEqual([c.code for c in C.search(self.all, "таганрог 10")], ["61MS0203"])
        self.assertEqual([c.code for c in C.search(self.all, "Таганрог 1")], ["61MS0194"])   # «1» не цепляет «10»
        self.assertEqual([c.code for c in C.search(self.all, "ростова")], ["61MS0001"])
        self.assertEqual(len(C.search(self.all, "")), 4)

    def test_header_matches_sample_wording(self):
        c = C.find_by_code(self.all, "61MS0203")
        self.assertEqual(C.header_text(c).splitlines(), [
            "**Мировому судье в Таганрогском судебном районе Ростовской области**",
            "**на судебном участке № 10**",
            "347900, Ростовская область, г. Таганрог, ул. Большая Бульварная, д. 8-3"])
        rostov = C.header_text(C.find_by_code(self.all, "61MS0001")).splitlines()[0]
        self.assertEqual(rostov, "**Мировому судье в Ворошиловском судебном районе г. Ростова-на-Дону**")
        odd = C.header_text(C.find_by_code(self.all, "30MS0001")).splitlines()
        self.assertEqual(odd[:2], ["**Мировому судье Кировского района г. Астрахани**", "**на судебном участке № 1**"])


class OverridesTest(unittest.TestCase):
    def test_judge_and_address_survive_reload_and_reach_header(self):
        import tempfile
        old = C.COURTS_PATH
        C.COURTS_PATH = Path(tempfile.mkdtemp()) / "courts.json"
        try:
            base = C.parse(SAMPLE)
            C.save("61", [c for c in base if c.code.startswith("61")])
            C.set_override("61MS0203", "Иванова Ирина Ивановна", "347900, г. Таганрог, ул. Ремесленная, д. 12/1")
            court = C.find_by_code(C.load()["courts"], "61MS0203")
            self.assertEqual(court.judge, "Иванова Ирина Ивановна")
            self.assertEqual(court.address, "347900, г. Таганрог, ул. Ремесленная, д. 12/1")
            self.assertEqual(court.base_address, "347900, Ростовская область, г. Таганрог, ул. Большая Бульварная, д. 8-3")
            lines = C.header_text(court).splitlines()
            self.assertEqual(lines[2], "Судья: Иванова Ирина Ивановна")
            self.assertTrue(lines[3].endswith("д. 12/1"))
            # повторная загрузка списка правки не стирает
            C.save("61", base[:1] + base[1:3])
            again = C.find_by_code(C.load()["courts"], "61MS0203")
            self.assertEqual(again.judge, "Иванова Ирина Ивановна")
            # судью можно искать по фамилии
            self.assertEqual([c.code for c in C.search(C.load()["courts"], "иванова")], ["61MS0203"])
            # пустые значения снимают правку; адрес, совпадающий с исходным, не хранится как правка
            C.set_override("61MS0203", "", "347900, Ростовская область, г. Таганрог, ул. Большая Бульварная, д. 8-3")
            self.assertEqual(C.find_by_code(C.load()["courts"], "61MS0203").judge, "")
            self.assertNotIn("61MS0203", C._read_file().get("overrides", {}))
        finally:
            C.COURTS_PATH = old


if __name__ == "__main__":
    unittest.main()


class RegionSelectTest(unittest.TestCase):
    def setUp(self):
        self.old = C.COURTS_PATH
        C.COURTS_PATH = Path(tempfile.mkdtemp()) / "courts.json"

    def tearDown(self):
        C.COURTS_PATH = self.old

    def test_labels_show_name_but_value_is_code(self):
        self.assertEqual(C.region_label("61"), "Ростовская область (61)")
        self.assertEqual(C.region_label("5"), "Республика Дагестан (05)")

    def test_codes_and_summary_for_several_regions(self):
        self.assertEqual(C.region_codes("61, 23;61 5"), ["61", "23", "05"])
        self.assertEqual(C.regions_summary("61"), "Ростовская область (61)")
        self.assertEqual(C.regions_summary("61, 23, 05"), "Ростовская область (61) и ещё 2")
        self.assertEqual(C.regions_summary(""), "Ростовская область (61)")

    def test_several_regions_are_stored_and_used_for_download(self):
        C.set_regions("61, 23")
        self.assertEqual(C.load()["regions"], "61, 23")

    def test_choice_is_remembered_without_losing_other_data(self):
        C.save("61", [C.Court("61MS0001", "Участок № 1", "адрес")], last="61MS0001")
        C.set_regions("23")
        d = C.load()
        self.assertEqual(d["regions"], "23")
        self.assertEqual(len(d["courts"]), 1)
        self.assertEqual(d["last"], "61MS0001")

    def test_all_codes_are_two_digits_and_names_unique(self):
        self.assertTrue(all(len(c) == 2 and c.isdigit() for c in C.REGIONS))
        self.assertEqual(len(set(C.REGIONS.values())), len(C.REGIONS))
