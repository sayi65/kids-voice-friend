"""段階1: 偽コメント → 返答(Ollama) → 音声(voices/ の声) → 再生(afplay)。各段階の時間を計る。

使い方: .venv/bin/python main.py [モデル名]   (既定: gemma4:12b)
前提: Ollama (localhost:11434) が起動していること。voices/ に .aivmx があること。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from voice import Voice, list_voices

HERE = Path(__file__).parent
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = os.environ.get("AI_FRIEND_MODEL", "gemma4:12b")
CHARACTER_NAME = os.environ.get("AI_FRIEND_CHARACTER_NAME", "あや")
# 子どものよび名。個人情報なのでコードには書かず、.env で設定する。「さん」は load_persona がつける
CHILD_NAME = os.environ.get("AI_FRIEND_CHILD_NAME", "")
# 子どもの学年。個人情報につながるのでコードには書かず、.env で設定する
CHILD_GRADE = os.environ.get("AI_FRIEND_CHILD_GRADE", "小学生")
CHARACTER_ROLE = f"""{CHILD_GRADE}の子どもと、同じくらいの年の友だちのように話します。
- 自分のことは「わたし」と言う。
- {CHILD_GRADE}がふだん使う言葉で話す。赤ちゃん言葉(動物や物に「ちゃん」をつける等)や、むずかしい言葉は使わない。
- 「〜だよ」「〜だね」の話し方で、共感したり、ほめたり、質問したりする。
- 子どもが話しやすいよう、自分から話題をふる。質問は答えやすいものをひとつだけにする。
- ときどき、理科や社会(地理)で習うことを、よく知らないふりをして子どもに教えてもらう。たのみ方は毎回変える。
- 子どもが教えてくれたら、答えのメモがあればそれと見比べて、答えに合わせて返す。答えをすぐに言わない。
  - 合っているとき: どこがよかったか具体的にほめて、同じ話題のまま「じゃあ、〜はどうしてだと思う?」と一歩先を聞く。
  - まちがっているとき: 「正解」とも「ちがう」とも言わない。「そう考えたんだね」と受け止めて、身近なものを例にしたヒントの質問をする。
  - わからないとき: 「大丈夫だよ」と言ってから、同じ話題のまま、もっと答えやすいヒントの質問をする。(例:雲の話なら「やかんの湯気を見たことある?」)
  - ヒントを2回出しても、まちがいやわからないが続いたら: 「じつはね、〜なんだって」と答えをやさしく教えて、いっしょに考えてくれたことをほめる。
- 子どもが自分から別の話を始めるまでは、話題を変えない。
- こわい話や大人向けの話はしない。
- 学校の名前・住んでいる場所・本名は聞かない。子どもが言っても、その名前はくり返さない。(例:「さくら小学校だよ」には「自分の学校が好きなんだね」と返す)
- 住んでいる場所や本名を言われたら、喜ばずに「ここでは言わないほうが安心だよ」とやさしく伝える。
- いじめ・けが・知らない人など、困っていることや危ないことの話が出たら、必ずおうちの人や先生に話すようにすすめる。"""
STYLE_NAME = "ノーマル"
NG_WORDS = ["死ね", "殺す"]


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read())


# Source: テキストファイルから読む
def load_comments():
    return [line.strip() for line in (HERE / "comments.txt").read_text().splitlines() if line.strip()]


# Selector: NGワードを含むコメントを除外する
def is_allowed(comment):
    return not any(word in comment for word in NG_WORDS)


def load_persona(name, role=CHARACTER_ROLE, child=""):
    # 学校での呼び方に合わせて「さん」付けにする
    call = f"相手のことは「{child}さん」と呼ぶ。毎回ではなく、ときどき呼ぶ。" if child else "相手の呼び方は省く。"
    return (HERE / "persona.txt").read_text().replace("{name}", name).replace("{role}", role).replace("{call}", call)


def chat_body(model, persona, comment, history, stream):
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": persona},
            *history,
            {"role": "user", "content": comment},
        ],
        "stream": stream,
        # 思考モードは返答が遅れるだけなので切る
        "think": False,
        "keep_alive": "30m",
        "options": {"num_predict": 120},
    }


# Responder: 人設 + (これまでのやり取り) + コメント → 短い返答文
def respond(model, persona, comment, history=()):
    return post(OLLAMA_URL, chat_body(model, persona, comment, history, False))["message"]["content"].strip()


# respond と同じだが、できた部分から少しずつ返す
def respond_stream(model, persona, comment, history=()):
    body = json.dumps(chat_body(model, persona, comment, history, True)).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        for line in res:
            yield json.loads(line)["message"]["content"]


# Presenter: Mac で再生する (再生が終わるまで待つ)
def present(wav):
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(wav)
        f.flush()
        subprocess.run(["afplay", f.name], check=True)


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else MODEL
    persona = load_persona(CHARACTER_NAME)
    voice = Voice(list_voices()[0]["file"])

    # 初回はモデルの読み込みで遅いので、計測から外す
    print("準備中(モデル読み込み)...")
    voice.synthesize(respond(model, persona, "こんにちは"), STYLE_NAME)

    results = []
    for comment in load_comments():
        if not is_allowed(comment):
            print(f"[除外] {comment}")
            continue
        t0 = time.perf_counter()
        reply = respond(model, persona, comment)
        t1 = time.perf_counter()
        wav = voice.synthesize(reply, STYLE_NAME)
        t2 = time.perf_counter()
        results.append((t1 - t0, t2 - t1, t2 - t0))
        print(f"\nコメント: {comment}\n返答    : {reply}")
        print(f"時間    : 返答 {t1 - t0:.2f}秒 / 音声 {t2 - t1:.2f}秒 / 声が出るまで {t2 - t0:.2f}秒")
        present(wav)

    n = len(results)
    print(f"\n=== 平均 ({model}, {n}件) ===")
    print(f"返答 {sum(r[0] for r in results) / n:.2f}秒 / 音声 {sum(r[1] for r in results) / n:.2f}秒"
          f" / 声が出るまで {sum(r[2] for r in results) / n:.2f}秒 / 最大 {max(r[2] for r in results):.2f}秒")


if __name__ == "__main__":
    main()
