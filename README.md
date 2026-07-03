# Streamlit in Snowflake 棚卸し差異確認アプリ

---

## 1. 構成

```text
sis-inventory-diff-app/
├── .streamlit/
│   └── secrets.toml
├── data/
│   ├── inventory_snapshot_seed.csv
│   └── physical_inventory_counts_upload.xlsx
├── sql/
│   └── init.sql
├── .gitignore
├── .python-version
├── app.py
├── environment.yml
├── poetry.lock
├── pyproject.toml
├── README.md
└── snowflake.yml
```

---

## 2. Snowflake側の事前準備

`sql/init.sql` を実行し、データベース・スキーマ・テーブルを作成します。

また、**INVENTORY_SNAPSHOT** には理論在庫データとして、以下のファイルを事前投入してください。

```bash
data/inventory_snapshot_seed.csv
```

---

## 3. ローカル開発

※ ローカル開発環境には、以下がインストールされている前提です。

- Python 3.11
- Poetry

### 3.1 秘密鍵・公開鍵の作成とSnowflakeへの鍵の登録

事前に、Snowflakeと接続するための鍵を作成します。
ターミナルで、以下のコマンドを順番に実行します。

```bash
# .sshフォルダ配下にsnowflakeフォルダを作成する
mkdir -p ~/.ssh/snowflake

# 秘密鍵の作成
openssl genrsa 2048 | openssl pkcs8 \
  -topk8 \
  -inform PEM \
  -out ~/.ssh/snowflake/<your_private_key_name>.p8 \
  -nocrypt

# 公開鍵の作成
openssl rsa \
  -in ~/.ssh/snowflake/<your_private_key_name>.p8 \
  -pubout \
  -out ~/.ssh/snowflake/<your_public_key_name>.pub

# 公開鍵の中身を確認し、コピー
cat ~/.ssh/snowflake/<your_public_key_name>.pub
```

上記の手順で秘密鍵・公開鍵の作成が完了したらSnowflake上で以下を実行する。

```sql
-- Snowflakeへの登録
ALTER USER <YOUR_USER> -- ご自身のアカウントのユーザー名
SET RSA_PUBLIC_KEY = '<PUBLIC_KEY_BODY>'; -- 先程コピーした公開鍵の中身
```

### 3.2 依存関係のインストールとSnowflakeへの接続テスト

ターミナルに戻って以下のコマンドを実行し、依存関係をダウンロードします。

```bash
# 依存関係のインストール
poetry install

# Snowflakeへの接続情報の追加（プライベートキーファイルを使用した認証）
poetry run snow connection add \
   --connection-name <your_connection_name> \
   --authenticator SNOWFLAKE_JWT \
   --private-key-file ~/.ssh/<your_public_key_name>.p8

# 作成した接続で接続テスト
poetry run snow connection test -c <your_connection_name>

# key・valueが出力されればOK
+----------------------------------------------------------------+
| key             | value                                        |
|-----------------+----------------------------------------------|
| Connection name | <your_connection_name>                       |
| Status          | OK                                           |
| Host            | xxx.aws.snowflakecomputing.com               |
| Account         | xxx                                          |
| User            | YOUR_NAME                                    |
| Role            | YOUR_ROLE                                    |
| Database        | YOUR_DATABASE                                |
| Warehouse       | YOUR_WAREHOUSE                               |
+----------------------------------------------------------------+
```

※ 参考1：[Snowflake接続の管理](https://docs.snowflake.com/ja/developer-guide/snowflake-cli/connecting/configure-connections)
※ 参考2：[キーペア認証とキーペアローテーション](https://docs.snowflake.com/ja/user-guide/key-pair-auth)

### 3.3 .streamlit/secrets.tomlの追加

ルートフォルダ直下に `.streamlit/secrets.toml` を作成し、Snowflakeの接続情報を設定してください。

```bash
[connections.snowflake]
account = "YOUR_ACCOUNT"
user = "YOUR_USER"
role = "YOUR_ROLE"
warehouse = "YOUR_WAREHOUSE"
database = "YOUR_DATABASE"
schema = "INVENTORY_DIFF_APP"
private_key_file = "~/.ssh/snowflake/<your_private_key_name>.p8"
```

上記3点が完了したら、以下のコマンドを順に実行し、Streamlitアプリを起動します。

```bash
poetry run streamlit run app.py
```

※ 参考1：[シークレットを管理し、Streamlitアプリを設定する](https://docs.snowflake.com/ja/developer-guide/streamlit/app-development/secrets-and-configuration)

---

## 4. デプロイ

`snowflake.yml` の `query_warehouse` を自分のWarehouse名に変更してから実行します。

```bash
poetry run snow streamlit deploy --replace --prune --open -c your_connection_name --database YOUR_DATABASE --schema INVENTORY_DIFF_APP
```

- `--replace`：Streamlitアプリが既に存在する場合は、それを置き換える。
- `--prune`：ステージングされたがローカルファイルシステムには存在しないファイルを削除する。
- `--open`：Streamlitアプリをブラウザで開く。
- `-c（--connection）`：config.toml ファイルで定義されている接続の名前。
- `--database`：使用するデータベースを指定。
- `--schema`：使用するデータベーススキーマを指定。

※ 参考1：[Streamlitアプリのデプロイ](https://docs.snowflake.com/ja/developer-guide/snowflake-cli/streamlit-apps/manage-apps/deploy-app)
※ 参考2：[snow streamlit deploy](https://docs.snowflake.com/ja/developer-guide/snowflake-cli/command-reference/streamlit-commands/deploy)

---
