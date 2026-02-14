"""Verify basic package import works."""


def test_import_wiz():
    import wiz
    assert wiz.__version__ == "0.1.0"


def test_import_cli():
    from wiz.cli import main
    assert main is not None
