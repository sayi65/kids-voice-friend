# あやとおしゃべり

子どもと声でおしゃべりする AI の友だちです。小学生向けに、理科や社会(地理)の話題を「教えて」とたのみ、子どもに説明してもらうことで復習につなげます。話し方は、`.env` で設定した学年に合わせます。

- **すべて Mac の中で動きます。** 会話の音声も文字も、インターネットには送りません(最初の準備でモデルをダウンロードするときだけ、ネットにつなぎます)。
- Mac のブラウザか、同じ Wi-Fi の iPhone で話せます。
- 子どもが黙っていると、キャラクターの方から話しかけます。

```
マイク(ブラウザ) → 文字にする(Whisper) → 返事を作る(Gemma / Ollama) → 声にする(Style-Bert-VITS2) → スピーカー(ブラウザ)
```

## 必要なもの

| もの | 条件 |
|---|---|
| Mac | Apple Silicon (M1 以降)。メモリ 32GB 以上を推奨(16GB でも動く可能性はあるが、返事がかなり遅くなる見込み) |
| ディスクの空き | 約 15GB |
| Homebrew | https://brew.sh |
| 声のファイル | `.aivmx` 形式(下の「声のファイル」) |
| iPhone(使う場合) | Mac と同じ Wi-Fi につながっていること |

## 準備

```bash
git clone <このリポジトリの URL> ai-friend
cd ai-friend
scripts/setup.sh
```

`scripts/setup.sh` が、次の 5 つをまとめて行います。途中で止まっても、もう一度実行すれば続きから進みます。

1. `uv`(Python の環境を作る道具)と `Ollama`(AI を動かす道具)を Homebrew で入れる
2. Ollama を起動する
3. 返事を作るモデル `gemma4:12b`(約 8GB)をダウンロードする
4. Python の環境 `.venv/` を作り、ライブラリを入れる
5. 音声認識のモデル(約 1.5GB)をダウンロードする

あわせて、設定ファイル `.env` を `.env.example` からコピーします。子どものよび名などは `.env` に書きます(下の「設定」)。

### 声のファイル

声のモデル(`.aivmx`)を、`voices/` フォルダに置きます。たとえば、AivisHub で配布されている「れな」の声を使う場合は次のとおりです。

1. https://hub.aivis-project.com/aivm-models/b1b8072f-809f-4c6d-9ba1-2ca94d9c3663 を開き、`.aivmx` をダウンロードする(約 250MB)
2. `voices/` に置く

ほかの `.aivmx` を `voices/` に入れると、画面の「せってい」→「声」から選べます。**一番新しく入れたものが最初から選ばれます。** 声のモデルごとに利用条件(ライセンス)があるので、配布ページで確かめてください。

AivisSpeech などのアプリは要りません。

## 起動

```bash
scripts/start.sh
```

Mac のブラウザで http://127.0.0.1:8765 を開き、「はじめる」を押します。初回はブラウザがマイクの許可を求めるので、「許可」を押してください。「1びょうだけ しずかにしてね」の間は静かにして、「きいているよ」になったら話しかけます。

止めるときは、ターミナルで `Ctrl + C` を押します。

## iPhone で使う

iPhone のブラウザは、安全な接続(https)のページでないとマイクを使わせません。そこで、家の Wi-Fi の中だけで使える証明書を作って、iPhone に信頼させます。

**家の Wi-Fi だけで使ってください。** 同じ Wi-Fi にいる人は、合言葉なしで画面を開けます。

1. `--lan` を付けて起動します。初回は証明書が `certs/` に作られます。

   ```bash
   scripts/start.sh --lan
   ```

   iPhone で開く URL(例: `https://192.168.0.10:8766`)が表示されます。

2. **初回だけ**、Mac の Finder で `certs/` を開き、**`rootCA.crt` だけ**を AirDrop で iPhone に送ります。
   - 同じフォルダの `rootCA-key.pem` と `key.pem` は秘密の鍵です。**誰にも送らないでください。**
   - Mac で `rootCA.crt` をダブルクリックしないでください(Mac に登録されてしまいます。Mac には登録しなくても使えます)。
3. iPhone で、**設定 → 一般 → VPN とデバイス管理** → 「AI friend local CA」→ **インストール**
4. **設定 → 一般 → 情報 → 証明書信頼設定** → 「AI friend local CA」を**オン**
5. iPhone の Safari で、1 で表示された URL を開き、「はじめる」を押してマイクを許可します。

この信頼の元は、家のネットワークの住所(192.168.x.x など)にしか使えないように制限してあります。

あとで消すときは、手順 3 の画面で「プロファイルを削除」を押します。

## 設定

`.env` を書き換えて、`scripts/start.sh` で起動し直します。

| 名前 | 内容 | 初期値 |
|---|---|---|
| `AI_FRIEND_CHILD_NAME` | 子どものよび名。「さん」は自動でつく。空なら名前では呼ばない | (空) |
| `AI_FRIEND_CHILD_GRADE` | 子どもの学年(例: 小学2年生)。話し方の目安にする | 小学生 |
| `AI_FRIEND_CHARACTER_NAME` | キャラクターの名前 | あや |
| `AI_FRIEND_MODEL` | 返事を作る Ollama のモデル | gemma4:12b |
| `AI_FRIEND_PORT` | Mac で開くポート(http) | 8765 |
| `AI_FRIEND_LAN_PORT` | iPhone で開くポート(https) | 8766 |

名前・声・役割・よび名は、画面の「せってい」でも、その回だけ変えられます。

## ファイル

| ファイル | 中身 |
|---|---|
| `voice_app.py` | サーバー。届いた音声を文字にして、返事を 1 文ずつ声にして返す |
| `index.html` | 画面。録音、話し終わりの判定、声の再生、アニメーション |
| `main.py` | 返事を作る部分、キャラクターの役割(`CHARACTER_ROLE`)。単体で実行すると、`comments.txt` の文で速さを測る |
| `voice.py` | 声のファイル(`.aivmx`)を読み込んで、文章を声にする |
| `persona.txt` | キャラクターの設定文の土台と、守らせるルール |
| `topics.txt` | キャラクターから話しかけるときの話題と、正しい答えのメモ。自由に足したり消したりできる |
| `scripts/` | 準備・起動・証明書づくり |

## 困ったとき

| 症状 | 対処 |
|---|---|
| 「Ollama が動いていません」 | Ollama アプリを起動するか、`brew services start ollama` を実行する |
| 返事が遅い | Mac のメモリが足りていない可能性が高い。ほかのアプリ(ブラウザのタブ、Docker など)を閉じるか、Mac を再起動する |
| 「マイクがつかえないよ」 | ブラウザの設定でマイクを許可する。iPhone は `https://` の URL で開く |
| iPhone で「この接続ではプライバシーが保護されません」と出る | 「iPhone で使う」の手順 3・4 を確かめる |
| Wi-Fi につなぎ直したら iPhone で開けない | Mac の IP アドレスが変わった。`scripts/start.sh --lan` で起動し直し、表示された新しい URL を開く(証明書は自動で作り直される) |

## 安全とプライバシー

- 会話の音声と文字は、Mac の中だけで処理します。会話の記録は、画面を閉じると消えます。
- キャラクターには、住所や本名を聞かない・くり返さない、政治や宗教の話に乗らない、困りごとはおうちの人や先生に相談するようすすめる、などのルールを入れています(`persona.txt`、`main.py` の `CHARACTER_ROLE`)。ただし AI なので、守れないことや、事実と違うことを言うことがあります。**子どもが使うときは、大人が近くで見守ってください。**

## ライセンスとクレジット

このリポジトリのコードは **AGPL-3.0** です(`LICENSE`)。使っている主なもの:

| もの | ライセンス |
|---|---|
| [Style-Bert-VITS2](https://github.com/tsukumijima/Style-Bert-VITS2)(声を作る) | AGPL-3.0 |
| [aivmlib](https://github.com/Aivis-Project/aivmlib)(声のファイルを読む) | MIT |
| [mlx-whisper](https://github.com/ml-explore/mlx-examples) / Whisper(音声認識) | MIT |
| [Gemma](https://ai.google.dev/gemma)(返事を作る) | Gemma Terms of Use |
| [Phosphor Icons](https://phosphoricons.com)(画面のアイコン) | MIT |
| [Zen Maru Gothic](https://fonts.google.com/specimen/Zen+Maru+Gothic)(画面の文字) | SIL Open Font License |

声のモデルは、このリポジトリに含めていません。使う声のモデルの利用条件に従ってください。上の「れな」の声は ACML 1.0 で配布されていて、制作者から次のクレジット表記が依頼されています。

> 声は (x.com/dopoiro) のAI
