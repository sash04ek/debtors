"""Изоляция тестов от данных пользователя: до импорта storage папка данных переключается на временную.
Каждый тестовый модуль первой строкой импортирует этот файл; без него App() читал бы и мог переписать реальные ~/.debtors."""
import os
import tempfile

HOME = tempfile.mkdtemp(prefix="debtors-test-")
os.environ["DEBTORS_HOME"] = HOME
