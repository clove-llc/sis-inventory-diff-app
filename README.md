# Streamlit in Snowflake 棚卸し差異確認アプリ

## 構成

```text
sis_inventory_app/
├── app/
│   └── streamlit_app.py
├── sql/
│   └── 001_create_tables.sql
├── snowflake.yml
├── environment.yml
├── pyproject.toml
└── README.md
```

## ローカル開発

```bash
pyenv install 3.11
pyenv local 3.11

poetry config virtualenvs.in-project true
poetry env use "$(pyenv which python)"
poetry install
poetry run streamlit run app/streamlit_app.py
```

ローカル実行時は `.streamlit/secrets.toml` にSnowflake接続情報を設定してください。

## 各種バージョン確認

```bash
poetry run python --version
poetry run streamlit --version
poetry run snow --version
```

## Snowflake側の準備

```sql
-- sql/001_create_tables.sql を実行
```

`INVENTORY_SNAPSHOT` には理論在庫データを事前投入してください。

## デプロイ

`snowflake.yml` の `query_warehouse` を自分のWarehouse名に変更してから実行します。

```bash
poetry run snow streamlit deploy --replace --prune --schema xxx
```
