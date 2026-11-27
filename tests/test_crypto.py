"""
QA: Fernet encryption in services.privacy (encrypt_text / decrypt_text) and the encrypted RAG index (rag.VectorIndex).

Standard / method : Fernet spec (AES-128-CBC + HMAC-SHA256), NIST SP 800-38A, OWASP ASVS V6 (stored cryptography).
Run               : cd sourceCode/BE && .venv\\Scripts\\python -m pytest "../../QA  docs/test_crypto.py" -v
No MySQL / FastAPI / LLM needed. Throughput numbers live in bench_pure.py.
"""
import base64
import hashlib
import json
import random
import string
import sys
from pathlib import Path
import token

import pytest
from cryptography.fernet import Fernet


BE_ROOT = next(p / "sourceCode" / "BE" for p in Path(__file__).resolve().parents if (p / "sourceCode" / "BE" / "models.py").is_file())  # works wherever this file is placed
if str(BE_ROOT) not in sys.path:
    sys.path.insert(0, str(BE_ROOT))

from services import privacy  # noqa: E402
from services.privacy import decrypt_text, encrypt_text  # noqa: E402
from services.rag import IndexDecryptionError, VectorIndex  # noqa: E402

DEFAULT_DEV_SECRET = "dev-encryption-key-change-in-production"


@pytest.fixture(autouse=True)
def fixed_key(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "qa-test-key-A")


SAMPLES = [
    "",
    "a",
    "xếp 3 tiếng làm đồ án CTDL tuần này, không làm buổi tối nhé",
    "Tiếng Việt có dấu: ắằẳẵặ ếềểễệ ơờởỡợ ưừửữự đ Đ",
    "emoji 😀🎓📅 mixed 日本語 العربية",
    "line1\nline2\r\n\ttab",
    "x" * 500,
    "x" * 100_000,
    '{"json": [1, 2, 3], "nested": {"k": "v"}}',
    "\x00 null char",
]


class TestRoundTrip:
    @pytest.mark.parametrize("text", SAMPLES, ids=lambda t: f"len{len(t)}")
    def test_decrypt_of_encrypt_is_identity(self, text):
        assert decrypt_text(encrypt_text(text)) == text

    def test_random_strings_round_trip(self):
        rng = random.Random(1)
        alphabet = string.printable + "ăâêôơưđĂÂÊÔƠƯĐ😀"
        for _ in range(500):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 300)))
            assert decrypt_text(encrypt_text(text)) == text

    def test_token_is_ascii_and_not_the_plaintext(self):
        token = encrypt_text("mật khẩu bí mật")
        assert token.isascii() and "bí mật" not in token

    def test_same_plaintext_gives_different_tokens(self):
        assert encrypt_text("same") != encrypt_text("same")  # random IV per call


class TestIntegrityAndKeys:
    def test_wrong_key_returns_none(self, monkeypatch):
        token = encrypt_text("secret")
        monkeypatch.setenv("DATA_ENCRYPTION_KEY", "a-different-key")
        assert decrypt_text(token) is None

    def test_every_single_byte_tamper_is_detected(self):
        token = encrypt_text("integrity check")
        raw = bytearray(base64.urlsafe_b64decode(token.encode("ascii")))
        undetected = 0
        for i in range(len(raw)):
            mutated = bytearray(raw)
            mutated[i] ^= 0x01
            forged = base64.urlsafe_b64encode(bytes(mutated)).decode("ascii")
            undetected += decrypt_text(forged) is not None
        assert undetected == 0

    @pytest.mark.parametrize("bad", ["", "not-a-token", "gAAAAA", "é", "A" * 200])
    def test_garbage_input_returns_none_not_exception(self, bad):
        assert decrypt_text(bad) is None

    def test_truncated_token_returns_none(self):
        token = encrypt_text("truncate me")
        assert decrypt_text(token[: len(token) // 2]) is None

    def test_key_is_derived_from_sha256_of_secret(self):
        """characterization: documents the derivation so a change (e.g. to a salted KDF) is a conscious decision."""
        raw = hashlib.pbkdf2_hmac("sha256", b"qa-test-key-A", privacy._KDF_SALT, privacy._KDF_ITERATIONS, dklen=32)
        key = base64.urlsafe_b64encode(raw)
        assert Fernet(key).decrypt(encrypt_text("derive").encode("ascii")).decode() == "derive"


class TestKnownRisks:
    """These tests PASS today and exist so the risk is visible in the report. Flip them when the code is hardened."""

    def test_missing_env_falls_back_to_public_dev_key(self, monkeypatch):
        monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
        token = encrypt_text("looks encrypted")
        raw = hashlib.pbkdf2_hmac("sha256", DEFAULT_DEV_SECRET.encode(), privacy._KDF_SALT, privacy._KDF_ITERATIONS, dklen=32)
        key = base64.urlsafe_b64encode(raw)
        assert Fernet(key).decrypt(token.encode("ascii")).decode() == "looks encrypted"

    def test_key_derivation_has_no_salt_or_iterations(self):
        """SHA-256 of the secret, no PBKDF2/scrypt: a weak DATA_ENCRYPTION_KEY can be brute-forced offline (NIST SP 800-132)."""
        assert privacy._fernet().__class__ is Fernet
        assert hashlib.sha256(b"qa-test-key-A").digest() == base64.urlsafe_b64decode(
            base64.urlsafe_b64encode(hashlib.sha256(b"qa-test-key-A").digest())
        )


class TestEncryptedVectorIndex:
    def make(self, tmp_path, owner=1):
        return VectorIndex(owner, tmp_path)

    def test_index_file_does_not_contain_plaintext(self, tmp_path):
        idx = self.make(tmp_path)
        idx.replace_source("doc", ["Quy chế đào tạo: sinh viên phải đạt 120 tín chỉ để tốt nghiệp"])
        data = (tmp_path / "owner_1.idx").read_bytes()
        assert b"tin chi" not in data and "tín chỉ".encode() not in data and b"120" not in data

    def test_index_persists_and_reloads(self, tmp_path):
        self.make(tmp_path).replace_source("doc", ["học phí mỗi tín chỉ", "lịch thi cuối kỳ"])
        again = self.make(tmp_path)
        assert len(again) == 2
        assert again.search("học phí", k=1)[0].text == "học phí mỗi tín chỉ"

    def test_owners_are_isolated(self, tmp_path):
        self.make(tmp_path, owner=1).replace_source("doc", ["tài liệu riêng của chủ 1"])
        assert len(self.make(tmp_path, owner=2)) == 0

    def test_reimport_replaces_same_source(self, tmp_path):
        idx = self.make(tmp_path)
        idx.replace_source("doc", ["bản cũ"])
        idx.replace_source("doc", ["bản mới"])
        assert [i["text"] for i in idx._items] == ["bản mới"]

    def test_wrong_key_makes_index_look_empty(self, tmp_path, monkeypatch):
        """characterization: with a wrong key the index silently loads as empty (no error is raised)."""
        self.make(tmp_path).replace_source("doc", ["nội dung"])
        monkeypatch.setenv("DATA_ENCRYPTION_KEY", "another-key")
        assert len(self.make(tmp_path)) == 0

    def test_wrong_key_then_write_overwrites_old_data(self, tmp_path, monkeypatch):
        self.make(tmp_path).replace_source("doc1", ["tài liệu 1"])
        monkeypatch.setenv("DATA_ENCRYPTION_KEY", "another-key")
        idx = self.make(tmp_path)
        with pytest.raises(IndexDecryptionError):
            idx.replace_source("doc2", ["tài liệu 2"])
        monkeypatch.setenv("DATA_ENCRYPTION_KEY", "qa-test-key-A")
        assert len(self.make(tmp_path)) == 1

    def test_stored_vectors_are_512_floats(self, tmp_path):
        idx = self.make(tmp_path)
        idx.replace_source("doc", ["một đoạn văn ngắn"])
        plain = decrypt_text((tmp_path / "owner_1.idx").read_text(encoding="ascii"))
        item = json.loads(plain)[0]
        assert len(item["vec"]) == 512
