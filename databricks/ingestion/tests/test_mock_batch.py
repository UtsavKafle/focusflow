import json

import pandas as pd

from databricks.ingestion.mock_smoke import prepare, publication_complete


def test_prepared_mock_manifest_tracks_actual_rows_and_quality(tmp_path):
    raw = tmp_path / "001"
    raw.mkdir()
    for signal, rate in (("hr", 1), ("eda", 4), ("acc", 8)):
        times = pd.date_range("2020-02-13 12:00:00", periods=rate * 60,
                              freq=pd.Timedelta(seconds=1 / rate))
        data = {"Timestamp": times.astype(str)}
        if signal == "acc":
            data.update(X=0, Y=0, Z=64)
        else:
            data["Value"] = [70 if signal == "hr" else 0.5] * len(times)
        if signal == "hr":
            data["Value"][3] = "NaN"
            data["Value"][4] = 0
        pd.DataFrame(data).to_csv(raw / f"{signal.upper()}_001.csv", index=False)
    output = tmp_path / "output"
    manifest = prepare(raw, output, "test", duration_minutes=1)
    assert manifest["expected_rows"] == 779
    assert manifest["files"]["hr"]["dropped"] == 1
    assert manifest["files"]["hr"]["flagged"] == 1
    assert manifest["files"]["acc"]["flagged"] == 480
    assert sum(m["row_count"] for m in manifest["local_markers"]) == 779
    rows = [json.loads(line) for marker in manifest["local_markers"]
            for line in open(marker["path"]).read().splitlines()]
    assert all(row["source_kind"] == "synthetic_fixture" for row in rows)
    assert rows[0]["source_timestamp"] == "2020-02-13T17:00:00Z"
    assert rows[0]["event_time"] == "2026-10-09T16:00:00Z"
    assert "001-hr-000000004" not in {row["event_id"] for row in rows}
    assert any(row["signal"] == "hr" and row["values"]["value"] == 0 and
               row["quality"] == "flagged" for row in rows)
    source = (output / "bronze_smoke_notebook.py").read_text()
    compile(source, "notebook", "exec")
    assert "rows.count() == 779" in source
    assert not publication_complete(manifest)
    manifest["remote_markers"] = manifest["local_markers"][:2]
    assert not publication_complete(manifest)
    manifest["remote_markers"] = list(manifest["local_markers"])
    assert publication_complete(manifest)
    manifest["remote_markers"].append(manifest["remote_markers"][0])
    assert not publication_complete(manifest)
