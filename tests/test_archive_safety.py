import io
import stat
import zipfile
from unittest.mock import patch

import pytest
from worker.analyzer import text_extractor as extractor


def make_zip(tmp_path, members):
    path = tmp_path / 'attachment.zip'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            archive.writestr(name, data)
    return str(path)


@pytest.mark.parametrize('name', ['../escape.docx', '/escape.pdf', 'C:\\escape.pdf', 'nested/../../escape.xls', '..\\escape.pdf'])
def test_reject_paths_before_parsing(tmp_path, name):
    path = make_zip(tmp_path, [('safe.docx', b'valid'), (name, b'bad')])
    with patch.object(extractor, 'extract_text_from_file') as parse:
        assert extractor.extract_text_from_archive(path) == ''
        parse.assert_not_called()
    assert not (tmp_path / 'escape.docx').exists()


def test_reject_symlink(tmp_path):
    member = zipfile.ZipInfo('link.docx')
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    path = make_zip(tmp_path, [(member, b'/tmp/secret')])
    with patch.object(extractor, 'extract_text_from_file') as parse:
        assert extractor.extract_text_from_archive(path) == ''
        parse.assert_not_called()


def test_reject_expansion_bomb_before_opening_member(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor, 'ARCHIVE_MAX_BYTES', 1024)
    path = make_zip(tmp_path, [('bomb.docx', b'0' * 100_000)])
    with patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('must not inflate')):
        assert extractor.extract_text_from_archive(path) == ''


def test_reject_excess_member_count(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor, 'ARCHIVE_MAX_MEMBERS', 1)
    path = make_zip(tmp_path, [('a.doc', b''), ('b.doc', b'')])
    with patch.object(extractor, 'extract_text_from_file') as parse:
        assert extractor.extract_text_from_archive(path) == ''
        parse.assert_not_called()


def test_actual_stream_size_checked(tmp_path, monkeypatch):
    path = make_zip(tmp_path, [('a.doc', b'x')])
    monkeypatch.setattr(extractor, 'ARCHIVE_MAX_BYTES', 5)
    with patch.object(zipfile.ZipFile, 'open', return_value=io.BytesIO(b'x' * 6)), patch.object(extractor, 'extract_text_from_file') as parse:
        assert extractor.extract_text_from_archive(path) == ''
        parse.assert_not_called()


def test_7z_fails_closed_without_extractor(tmp_path):
    assert extractor.extract_text_from_archive(str(tmp_path / 'file.7z')) == ''


def test_text_collection_stops_consuming_at_limit(monkeypatch):
    monkeypatch.setattr(extractor, 'EXTRACTED_TEXT_MAX_CHARS', 4)
    def parts():
        yield 'abcdef'
        raise AssertionError('must stop reading once full')
    assert extractor._join_bounded(parts()) == 'abcd'


def test_office_package_bomb_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor, 'ARCHIVE_MAX_BYTES', 10)
    path = make_zip(tmp_path, [('xl/sharedStrings.xml', b'0' * 100)])
    with patch('openpyxl.load_workbook') as parse:
        assert extractor.extract_text_from_xlsx(path) == ''
        parse.assert_not_called()


@pytest.mark.parametrize('metadata', [
    {},
    {'is_symlink': lambda: True},
    {'is_symlink': lambda: False, 'file_redir': (1, 0, 'outside')},
])
def test_rar_rejects_links_or_unknown_metadata(metadata):
    from types import SimpleNamespace
    member = SimpleNamespace(filename='a.doc', file_size=1, **metadata)
    with pytest.raises(ValueError, match='link metadata'):
        extractor._validate_members([member], rar=True)


def test_rar_streaming(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    member = SimpleNamespace(filename='a.doc', file_size=3, is_symlink=lambda: False, file_redir=None)
    archive = MagicMock()
    archive.infolist.return_value = [member]
    archive.open.return_value = io.BytesIO(b'doc')
    def parse(path):
        assert open(path, 'rb').read() == b'doc'
        return 'parsed document'
    with patch('rarfile.RarFile', return_value=archive), patch.object(extractor, 'extract_text_from_file', side_effect=parse):
        assert 'parsed document' in extractor.extract_text_from_archive(str(tmp_path / 'a.rar'))
    archive.extractall.assert_not_called()


def test_xlsx_closes_and_stops_reading_rows(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(extractor, 'EXTRACTED_TEXT_MAX_CHARS', 4)
    path = make_zip(tmp_path, [])
    workbook = MagicMock()
    sheet = MagicMock()
    def rows(**kwargs):
        assert kwargs['max_col'] == extractor.SPREADSHEET_MAX_COLUMNS
        yield ('abcdef',)
        raise AssertionError('must not consume more rows')
    sheet.iter_rows.side_effect = rows
    workbook.worksheets = [sheet]
    with patch('openpyxl.load_workbook', return_value=workbook):
        assert extractor.extract_text_from_xlsx(path) == 'abcd'
    workbook.close.assert_called_once()
