"""データファイルの暗号化（合言葉を知らない人には中身が読めないようにする）。

GitHub Pages の無料プランは誰でもアクセスできるページになる。そのまま置くと、
Yahoo Finance 由来の株価を誰でも見られる形で再配布することになるうえ、
自分用のアプリが他人にも見えてしまう。そこで全データを暗号化して置き、
画面側（ブラウザの Web Crypto）で合言葉から鍵を作って復号する。

    鍵   = PBKDF2-HMAC-SHA256(合言葉, salt, 600,000回) → 256bit
    中身 = gzip(JSON) を AES-256-GCM で暗号化。ファイルは [IV 12バイト][暗号文＋認証タグ]

gzip を先にかけるのは、暗号化した後のデータは圧縮が効かない（配信時の自動圧縮も効かない）ため。
salt は秘密ではない（同じ合言葉でもアプリごとに鍵が変わるようにするためのもの）ので
リポジトリに置いておき、毎日同じものを使う。毎日変えると、スマホ側で鍵を毎回
作り直す（数秒かかる）ことになる。
"""
import base64
import gzip
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

CONFIG = Path(__file__).resolve().parent / "crypto.json"
ITERATIONS = 600_000   # OWASP の推奨値（PBKDF2-HMAC-SHA256）


def load_config() -> dict:
    """salt と反復回数。無ければ作る（初回だけ）。"""
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    cfg = {"salt": base64.b64encode(os.urandom(16)).decode(), "iterations": ITERATIONS}
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return cfg


def derive_key(passphrase: str, cfg: dict) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=base64.b64decode(cfg["salt"]), iterations=int(cfg["iterations"]))
    return kdf.derive(passphrase.encode("utf-8"))


def seal(obj, key: bytes) -> bytes:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    packed = gzip.compress(raw, compresslevel=9, mtime=0)
    iv = os.urandom(12)
    return iv + AESGCM(key).encrypt(iv, packed, None)


def open_sealed(blob: bytes, key: bytes):
    """テスト用（画面側と同じ手順で戻せることの確認）。"""
    packed = AESGCM(key).decrypt(blob[:12], blob[12:], None)
    return json.loads(gzip.decompress(packed).decode("utf-8"))
