# curly-giggle — The Catalyst 動画自動生成

台本(JSON)を1つ書くと、次のものを自動で作ります。

| 出力 | 内容 |
|---|---|
| `out/<slug>/<slug>.mp4` | 横長の本編(1920x1080 / 30fps、ナレーション・字幕・BGM入り) |
| `out/<slug>/<slug>_reel.mp4` | 縦長リール(1080x1920、59秒以内) |
| `out/<slug>/thumbnail.jpg` | YouTube用サムネイル(1280x720) |
| `out/<slug>/youtube.txt` | タイトル・概要欄(チャプターの時刻は自動計算)・ハッシュタグ |

外部の素材サイトや有料APIは使いません。ナレーションはローカルのKokoro TTS、映像は自前で描くモーショングラフィックス、BGMはプログラムで合成しています。著作権の心配がない素材だけで作れます。

## 使い方

```bash
pip install -r requirements.txt     # ffmpeg も必要
./fetch_models.sh                   # 音声モデル(約350MB)を models/ に取得
python -m catalyst.build episodes/ai-power-problem/script.json
```

一部だけ作り直すときは `--only main|reel|thumb` を付けます。ナレーション音声は `out/<slug>/tts/` にキャッシュされるので、台本を直した文だけが再生成されます。

## 台本の書き方(`episodes/<slug>/script.json`)

- `scenes[]` が1場面ずつの指定です。`say` が読み上げる文で、字幕もこの文から作ります。
- `chapter` を書いた場面からチャプターが始まり、概要欄のタイムスタンプになります。
- `visual.type` で画面の種類を選びます。

| type | 画面 |
|---|---|
| `title` | 大見出し |
| `card` | チャプター扉 |
| `text` | 1行ずつ出る強調テキスト(`*ここ*` がアクセント色) |
| `icon` | アイコン+見出し(`tower` `bolt` `chip` `drop` `flame` `house`) |
| `stat` | 数字のカウントアップ |
| `bars` | 棒グラフ(`hi` で範囲、`note` で注記、`color: "muted"` で灰色) |
| `list` | 箇条書き(`numbered` で番号付き) |
| `timeline` | 年表 |
| `versus` | 2つの立場の比較 |

`accent: "red"` で場面の色を赤にできます。`source` を書くと画面左下に出典が出ます。

- `reel.scenes` にリールに使う場面IDを並べます。`max_seconds` を超える分は後ろから外します。
- `voice` はKokoroの声(既定 `af_heart`)、`speed` は話す速さです。

## 公開の流れ

1. ビルドして本編・リールを確認する
2. `catalyst-video-host` に動画を置く(Bufferが読み込める公開URLにするため)
3. Buffer で YouTube(本編)と Instagram(リール)に予約投稿する。本文は `youtube.txt` を使う
