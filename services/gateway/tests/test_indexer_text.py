

def test_file_diversi_stesso_project_non_collidono(tmp_path):
    """Il bug del 06/09 (#285): tre doc sotto lo STESSO project collassavano
    perché la key uuid era il solo project → sha1(project, indice) identico
    fra file diversi → «deduplicati» dal secondo in poi. La key ora include
    il nome file: contenuti diversi convivono, il re-index dello stesso file
    resta idempotente."""
    from app.archive_indexer import _iter_text
    a = tmp_path / "doc1.md"
    a.write_text("alfa uno\n\nalfa due", encoding="utf-8")
    b = tmp_path / "doc2.md"
    b.write_text("beta uno\n\nbeta due", encoding="utf-8")
    rows_a = list(_iter_text(a, "video:prova"))
    rows_b = list(_iter_text(b, "video:prova"))
    uid_a = {r[0] for r in rows_a}
    uid_b = {r[0] for r in rows_b}
    assert uid_a and uid_b
    assert not (uid_a & uid_b), "uuid collidono fra file diversi: la dedup li mangerebbe"
    # idempotenza sul medesimo file: stessi uuid a ogni passata
    assert uid_a == {r[0] for r in list(_iter_text(a, "video:prova"))}
