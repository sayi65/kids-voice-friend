"""音声会話: ブラウザで録音し、話し終わるたびに届く音声を文字にして、返事の声を返す。

使い方: scripts/start.sh        → Mac のブラウザで http://127.0.0.1:8765 を開く
       scripts/start.sh --lan  → iPhone からは https://<Mac の Wi-Fi の IP>:8766 も開ける
                                 (家の Wi-Fi だけで使う。合言葉なし。certs/ の証明書を使う)
設定は .env (見本は .env.example)。準備は scripts/setup.sh。
"""
import base64
import json
import os
import random
import re
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mlx_whisper
import numpy as np

import main
from voice import Voice, list_voices

PORT = int(os.environ.get("AI_FRIEND_PORT", "8765"))
# iPhone のブラウザは https でないとマイクを使わせないので、Wi-Fi 向けは https で別に開く
LAN_PORT = int(os.environ.get("AI_FRIEND_LAN_PORT", "8766"))
CERTS = main.HERE / "certs"
RATE = 16000
WHISPER_REPO = "mlx-community/whisper-large-v3-turbo"
HISTORY_TURNS = 6  # 返事に渡す直近のやり取りの往復数
# 子どもが話しかけてこないときに、キャラクターから話しかけさせるための指示
NUDGE = ("(子どもはまだ何も話していません。「{topic}」について、あなたはよく知らないふりをして、"
         "子どもに「教えて」とたのむ質問をひとつしてください。短く、答えやすく)")
# 答えのメモがある話題では、子どもの答えと見比べて合っているかを判断させる(別に問い合わせると遅くなるため)
NUDGE_MEMO = ("(答えのメモ: {answer}。このメモは子どもが考える前には言わず、子どもの答えが合っているかを"
              "判断するときに使う)")
RECENT_TOPICS = 5  # 直近に使った話題はくり返さない
FILLERS = ["うんうん", "ふむふむ"]
MATH_TOKENS = 320  # 算数モードの返事の長さの上限(ボードの書き込みも含む)
# 返事の中の [[式 12 ÷ 3 = 4]] のような、ボードに書く指示
TAG = re.compile(r"\[\[(.*?)\]\]", re.S)
BOARD_COMMANDS = {"式", "点", "箱", "数直線", "消す"}
TEACH = ("(子どもが次の問題を教えてほしいと言っています。問題:「{problem}」。"
         "最初の一歩だけを、ボードに書きながら教えて、答えやすい質問をひとつしてください。答えは言わないでください)")
MAX_PHOTOS = 6
READ_PROBLEM = ("この画像に書かれている算数・数学の問題を、そのまま日本語の文字で書き写してください。"
                "図がある場合は、図の内容も短く説明してください。前置きや解説は不要で、問題の文だけを書いてください。"
                "画像が複数あるときは、送られた順に、1つの問題の続き、または別の問題として書いてください。"
                "問題がいくつかあるときは、「(1)」「(2)」のように番号をつけて分けてください。")
# ここで区切って1文ずつ声にする
SENTENCE_END = re.compile(r"[。！？!?\n]+")
# 声を作る時間は文の長さにほぼ比例するので、最初の声だけは読点でも区切って早く出す
FIRST_END = re.compile(r"[。！？!?\n、,]+")
FIRST_MIN = 6  # 文字。これより短い固まりでは区切らない(「ねえ、」だけで切ると不自然なため)
WARM_INTERVAL = 2  # 秒。3秒以上あけると温め自体が遅くなる回が出た

# スマホ(やパソコン)から届いた問題の写真。パソコンの画面に並べて、子どもが選んだものを読む
MAX_STORED = 20
photos = []  # [{"id": 番号, "image": base64}]
photo_seq = 0

LAN_ON = "--lan" in sys.argv

# 今の会話。START で作り、STOP で消す(使う人は一度に1人の想定)
session = None
# 一度読み込んだ声は START のたびに読み直さない
loaded_voices = {}


# Mac のメモリが足りないと、数秒使わないだけで LLM の重みが圧縮され、次の返事が3〜4秒遅れる。
# 会話中は小さな問い合わせで使い続けて、圧縮させない(Ollama の use_mlock は MLX 方式では効かなかった)
def keep_warm(s):
    while not s["stop"].is_set():
        if not s["responding"].is_set():
            main.post(main.OLLAMA_URL, {
                "model": main.MODEL, "messages": [{"role": "user", "content": "ん"}],
                "stream": False, "think": False, "keep_alive": "30m", "options": {"num_predict": 1},
            })
        s["stop"].wait(WARM_INTERVAL)


def start(body):
    global session
    stop()
    voices = {v["file"]: v for v in list_voices()}
    voice_file = body.get("voice") if body.get("voice") in voices else next(iter(voices))
    styles = voices[voice_file]["styles"]
    if voice_file not in loaded_voices:
        loaded_voices[voice_file] = Voice(voice_file)
    name = body.get("name", "").strip() or main.CHARACTER_NAME
    role = body.get("role", "").strip() or main.CHARACTER_ROLE
    child = body.get("child", "").strip()
    session = {
        "name": name,
        "role": role,
        "child": child,
        "math": bool(body.get("math")),
        "persona": main.load_persona(name, role, child, bool(body.get("math"))),
        "voice": loaded_voices[voice_file],
        "style": body.get("style") if body.get("style") in styles else styles[0],
        "history": [],
        "recent": [],
        "stop": threading.Event(),
        "responding": threading.Event(),
    }
    threading.Thread(target=keep_warm, args=(session,), daemon=True).start()
    # 話し終わってすぐ流すあいづち。返事ができるまでの待ち時間を短く感じさせる
    return [b64(session["voice"].synthesize(t, session["style"])) for t in FILLERS]


def b64(wav):
    return base64.b64encode(wav).decode()


# 話の途中で、ふつうのおしゃべりと算数ボードを切り替える。会話の記録は引きつがない
def set_mode(s, math):
    s["math"] = math
    s["persona"] = main.load_persona(s["name"], s["role"], s["child"], math)
    s["history"] = []


# 写真に写っている問題を、文字にして返す。子どもが確かめて直せるよう、すぐには教え始めない
def read_problem(images):
    res = main.post(main.OLLAMA_URL, {
        "model": main.MODEL, "stream": False, "think": False, "keep_alive": "30m", "options": {"num_predict": 600},
        "messages": [{"role": "user", "content": READ_PROBLEM, "images": images[:MAX_PHOTOS]}],
    })
    return res["message"]["content"].strip()


def add_photos(images):
    global photo_seq
    ids = []
    for image in images[:MAX_STORED]:
        photo_seq += 1
        photos.append({"id": photo_seq, "image": image})
        ids.append(photo_seq)
    del photos[:-MAX_STORED]
    return ids


def stored_images(ids):
    by_id = {p["id"]: p["image"] for p in photos}
    return [by_id[i] for i in ids if i in by_id]


# 返事から、ボードへの指示を取り出す。] がまだ届いていない途中の指示は、次に持ちこす
def take_tags(buf):
    cmds = []

    def grab(m):
        name, _, args = m.group(1).strip().partition(" ")
        if name in BOARD_COMMANDS:
            cmds.append([name, args.strip()])
        return ""

    clean = TAG.sub(grab, buf)
    i = clean.find("[[")
    if i >= 0:
        return clean[:i], cmds, clean[i:]
    if clean.endswith("["):
        return clean[:-1], cmds, "["
    return clean, cmds, ""


def nudge_prompt(s):
    lines = (main.HERE / "topics.txt").read_text().splitlines()
    topics = [t.strip() for t in lines if t.strip() and not t.startswith("#")]
    line = random.choice([t for t in topics if t not in s["recent"]] or topics)
    s["recent"] = (s["recent"] + [line])[-RECENT_TOPICS:]
    topic, _, answer = (part.strip() for part in line.partition("|"))
    return NUDGE.format(topic=topic) + (NUDGE_MEMO.format(answer=answer) if answer else "")


def stop():
    global session
    if session:
        session["stop"].set()
    session = None


# 届いた音声を文字にして、返事を1文ずつ声にして返す(できた順にイベントを返す)
def reply_to(s, raw, rate):
    audio = np.frombuffer(raw, dtype=np.float32)
    if rate != RATE:
        audio = np.interp(np.arange(0, len(audio), rate / RATE), np.arange(len(audio)), audio).astype(np.float32)
    t0 = time.perf_counter()
    text = mlx_whisper.transcribe(audio, path_or_hf_repo=WHISPER_REPO, language="ja")["text"].strip()
    if not text:
        yield {"type": "empty"}
        return
    yield {"type": "you", "name": s["name"], "text": text}
    yield from speak(s, text, t0, f"認識 {time.perf_counter() - t0:.1f}秒 / ")


def next_cut(text, is_first):
    if is_first:
        for m in FIRST_END.finditer(text):
            if m.start() >= FIRST_MIN:
                return m
    return SENTENCE_END.search(text)


# user_content への返事を作り、1文できるたびに声にして返す
def speak(s, user_content, t0, recognized=""):
    reply, pending, first, mark = "", "", None, {}
    held, cmds = "", []  # held: まだ ]] が届いていない指示。cmds: 次の文といっしょに送るボードへの指示
    math = s["math"]
    s["responding"].set()
    try:
        for piece in main.respond_stream(main.MODEL, s["persona"], user_content, s["history"],
                                         MATH_TOKENS if math else 120):
            reply += piece
            clean, new, held = take_tags(held + piece)
            cmds += new
            pending += clean
            while (m := next_cut(pending, first is None)):
                sentence, pending = pending[:m.end()].strip(), pending[m.end():]
                if sentence:
                    mark.setdefault("text", time.perf_counter())
                    yield {"type": "audio", "text": sentence, "draw": cmds,
                           "audio": b64(s["voice"].synthesize(sentence, s["style"]))}
                    cmds = []
                    first = first or time.perf_counter()
    finally:
        s["responding"].clear()
    if pending.strip():
        mark.setdefault("text", time.perf_counter())
        yield {"type": "audio", "text": pending.strip(), "draw": cmds,
               "audio": b64(s["voice"].synthesize(pending.strip(), s["style"]))}
        cmds = []
        first = first or time.perf_counter()
    if cmds:
        yield {"type": "draw", "draw": cmds}
    s["history"] = (s["history"] + [
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": reply.strip()},  # 指示つきで残すと、次もボードの書き方がそろう
    ])[-HISTORY_TURNS * 2:]
    now = time.perf_counter()
    first = first or now
    text_at = mark.get("text", now)
    yield {"type": "done", "times": f"{recognized}1文目の文 {text_at - t0:.1f}秒 / 1文目の声 {first - t0:.1f}秒 / 全部 {now - t0:.1f}秒"}


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # 1行に1つの JSON を、できた順に送る。長さが先に分からないので、送り終えたら接続を閉じて終わりを知らせる
    def send_events(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.end_headers()
        try:
            for event in events:
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode())
                self.wfile.flush()
        except Exception as e:
            self.wfile.write((json.dumps({"type": "error", "error": f"エラーで止まりました: {e}"}, ensure_ascii=False) + "\n").encode())

    def do_GET(self):
        if self.path == "/":
            self.send(200, (main.HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/photo":
            self.send(200, (main.HERE / "photo.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/photos":
            self.send(200, {"ids": [p["id"] for p in photos]})
        elif self.path.startswith("/photos/") and self.path.endswith(".jpg"):
            image = stored_images([int(self.path[8:-4] or 0)])
            if image:
                self.send(200, base64.b64decode(image[0]), "image/jpeg")
            else:
                self.send(404, {"error": "not found"})
        elif self.path == "/defaults":
            ip = CERTS / "ip.txt"
            photo_url = f"https://{ip.read_text().strip()}:{LAN_PORT}/photo" if LAN_ON and ip.exists() else ""
            self.send(200, {"photo_url": photo_url, "name": main.CHARACTER_NAME, "role": main.CHARACTER_ROLE, "child": main.CHILD_NAME,
                            "style": main.STYLE_NAME, "voices": list_voices()})
        else:
            self.send(404, {"error": "not found"})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            if self.path == "/start":
                self.send(200, {"fillers": start(json.loads(raw or b"{}"))})
            elif self.path == "/stop":
                stop()
                self.send(200, {"ok": True})
            elif self.path == "/read":
                images = stored_images(json.loads(raw).get("ids", []))[:MAX_PHOTOS]
                if not images:
                    self.send(400, {"error": "しゃしんが えらばれていません"})
                else:
                    self.send(200, {"text": read_problem(images)})
            elif self.path == "/photo/delete":
                gone = set(json.loads(raw).get("ids", []))
                photos[:] = [p for p in photos if p["id"] not in gone]
                self.send(200, {"ok": True})
            elif self.path == "/photo":
                self.send(200, {"ids": add_photos(json.loads(raw)["images"])})
            elif self.path == "/mode":
                if session:
                    set_mode(session, bool(json.loads(raw).get("math")))
                self.send(200, {"ok": True})
            elif self.path in ("/utterance", "/nudge", "/teach"):
                s = session
                if s is None:
                    self.send(409, {"error": "会話が始まっていません。「はじめる」を押してください"})
                elif self.path == "/teach":
                    problem = json.loads(raw)["problem"].strip()[:600]
                    set_mode(s, True)
                    self.send_events(speak(s, TEACH.format(problem=problem), time.perf_counter()))
                elif self.path == "/nudge":
                    self.send_events(speak(s, nudge_prompt(s), time.perf_counter()))
                else:
                    self.send_events(reply_to(s, raw, int(self.headers["X-Sample-Rate"])))
            else:
                self.send(404, {"error": "not found"})
        except Exception as e:
            self.send(500, {"error": f"エラーで止まりました: {e}"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("音声認識のモデルを読み込んでいます...")
    mlx_whisper.transcribe(np.zeros(RATE, dtype=np.float32), path_or_hf_repo=WHISPER_REPO, language="ja")
    local = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"準備できました。Mac のブラウザで http://127.0.0.1:{PORT} を開いてください (終了は Ctrl+C)")
    if "--lan" in sys.argv:
        lan = ThreadingHTTPServer(("0.0.0.0", LAN_PORT), Handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(CERTS / "cert.pem", CERTS / "key.pem")
        lan.socket = tls.wrap_socket(lan.socket, server_side=True)
        threading.Thread(target=lan.serve_forever, daemon=True).start()
        print(f"iPhone からは https://<この Mac の Wi-Fi の IP アドレス>:{LAN_PORT} を開いてください")
    local.serve_forever()
