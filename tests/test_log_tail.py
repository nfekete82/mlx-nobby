"""Log API regressions without reading private runtime logs."""

from io import BytesIO
from pathlib import Path

import pytest

from agent.log_tail import BLOCK_BYTES, MAX_TAIL_BYTES, read_log_tail


@pytest.mark.parametrize("content", [
    b"", b"one", b"one\n", b"one\n\n", b"one\r\ntwo\r\nthree",
    "Grüße\n日本語\nlast\n".encode(), b"invalid\xff\nlast\x00\n",
    b"old line\n" * 20_000 + "ä\nfinal".encode(),
])
@pytest.mark.parametrize("limit", [1, 3, 400])
def test_tail_matches_existing_line_contract(tmp_path, content, limit):
    path = tmp_path / "service.log"
    path.write_bytes(content)
    assert read_log_tail(path, limit) == content.decode(errors="replace").splitlines()[-limit:]


def test_large_unterminated_line_has_a_hard_read_bound():
    class TrackingStream(BytesIO):
        bytes_read = 0

        def read(self, size=-1):
            assert 0 <= size <= BLOCK_BYTES
            chunk = super().read(size)
            self.bytes_read += len(chunk)
            return chunk

    stream = TrackingStream(b"x" * (2 * MAX_TAIL_BYTES))

    class Log:
        def open(self, mode):
            assert mode == "rb"
            return stream

    assert read_log_tail(Log(), 400) == ["x" * MAX_TAIL_BYTES]
    assert stream.bytes_read == MAX_TAIL_BYTES


def test_byte_capped_tail_drops_incomplete_first_line(tmp_path):
    path = tmp_path / "huge.log"
    path.write_bytes(b"x" * (2 * MAX_TAIL_BYTES) + b"\nlast\n")
    assert read_log_tail(path, 400) == ["last"]


def test_utf8_sequence_spanning_read_blocks(tmp_path):
    path = tmp_path / "utf8.log"
    content = ("ä" * 70_001 + "\n日本語\nlast").encode()
    path.write_bytes(content)
    assert read_log_tail(path, 3) == content.decode().splitlines()


def test_both_log_apis_use_the_bounded_reader(tmp_path, monkeypatch):
    from agent import app as agent

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log = tmp_path / "mlx-web/agent.log"
    log.parent.mkdir()
    log.write_bytes(b"old\n" * 100 + b"clean\x00\nlast\n")
    monkeypatch.setattr(agent, "JOBS", {})

    # Prevent regressions to the old full-file read, including in either API.
    def forbidden(*args, **kwargs):
        raise AssertionError("Log APIs must not read the entire file")

    monkeypatch.setattr(Path, "read_text", forbidden)
    sources = agent.collect_log_sources(2)
    assert next(item for item in sources if item["id"] == "agent")["lines"] == ["clean", "last"]
    assert agent.mlx_log_lines(2) == [{"file": str(log), "lines": ["clean\x00", "last"]}]


def test_missing_file_remains_an_os_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_log_tail(tmp_path / "missing.log", 20)
