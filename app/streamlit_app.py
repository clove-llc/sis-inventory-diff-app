from __future__ import annotations

from io import BytesIO
from typing import Iterable

import pandas as pd
import streamlit as st

APP_TITLE = "棚卸し差異確認アプリ"
INVENTORY_TABLE = "INVENTORY_SNAPSHOT"
COUNTS_TABLE = "PHYSICAL_INVENTORY_COUNTS"
REQUIRED_COLUMNS = ["COUNT_DATE", "STORE_ID", "PRODUCT_ID", "ACTUAL_STOCK_QTY"]


st.set_page_config(page_title=APP_TITLE, layout="wide")


@st.cache_resource(show_spinner=False)
def get_session():
    """SnowflakeのSnowpark Sessionを取得する。"""
    conn = st.connection("snowflake")
    return conn.session()


def fetch_pandas(sql: str) -> pd.DataFrame:
    """SnowflakeのSQL実行結果をpandas DataFrameとして返す。"""
    return get_session().sql(sql).to_pandas()


def execute(sql: str) -> None:
    """SnowflakeでSQLを実行する。"""
    get_session().sql(sql).collect()


def get_current_user() -> str:
    """登録者情報としてSnowflakeのCURRENT_USERを使う。"""
    df = fetch_pandas("SELECT CURRENT_USER() AS USER_NAME")
    return str(df.loc[0, "USER_NAME"])


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Excelの列名をSnowflakeに合わせて大文字スネークケースに寄せる。"""
    normalized = df.copy()
    normalized.columns = [
        str(col).strip().upper().replace(" ", "_") for col in normalized.columns
    ]
    return normalized


def validate_upload_df(df: pd.DataFrame) -> tuple[pd.DataFrame | None, list[str]]:
    """アップロードされた実棚卸データを検証し、登録用DataFrameを返す。"""
    errors: list[str] = []
    df = normalize_columns(df)

    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_columns:
        errors.append(f"必要な列が不足しています: {', '.join(missing_columns)}")
        return None, errors

    df = df[REQUIRED_COLUMNS].copy()

    df["COUNT_DATE"] = pd.to_datetime(df["COUNT_DATE"], errors="coerce").dt.date
    df["STORE_ID"] = df["STORE_ID"].astype(str).str.strip()
    df["PRODUCT_ID"] = df["PRODUCT_ID"].astype(str).str.strip()
    df["ACTUAL_STOCK_QTY"] = pd.to_numeric(df["ACTUAL_STOCK_QTY"], errors="coerce")

    if df["COUNT_DATE"].isna().any():
        errors.append("COUNT_DATEに日付として解釈できない値があります。")
    if (df["STORE_ID"] == "").any():
        errors.append("STORE_IDが空の行があります。")
    if (df["PRODUCT_ID"] == "").any():
        errors.append("PRODUCT_IDが空の行があります。")
    if df["ACTUAL_STOCK_QTY"].isna().any():
        errors.append("ACTUAL_STOCK_QTYに数値として解釈できない値があります。")
    if (df["ACTUAL_STOCK_QTY"] < 0).any():
        errors.append("ACTUAL_STOCK_QTYに負の値があります。")

    duplicated = df.duplicated(subset=["COUNT_DATE", "STORE_ID", "PRODUCT_ID"], keep=False)
    if duplicated.any():
        errors.append("COUNT_DATE、STORE_ID、PRODUCT_IDの組み合わせが重複しています。")

    if errors:
        return None, errors

    df["ACTUAL_STOCK_QTY"] = df["ACTUAL_STOCK_QTY"].astype(int)
    df["UPLOADED_AT"] = pd.Timestamp.utcnow().tz_localize(None)
    df["UPLOADED_BY"] = get_current_user()

    return df, []


def sql_literal(value: object) -> str:
    """簡易的なSQLリテラル化。この記事用の少量データを前提にする。"""
    if pd.isna(value):
        return "NULL"
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def replace_physical_counts(df: pd.DataFrame) -> int:
    """同じ棚卸日・店舗IDの既存データを削除してから、アップロードデータをINSERTする。"""
    session = get_session()

    keys = df[["COUNT_DATE", "STORE_ID"]].drop_duplicates()
    for _, row in keys.iterrows():
        count_date = sql_literal(row["COUNT_DATE"])
        store_id = sql_literal(row["STORE_ID"])
        execute(
            f"""
            DELETE FROM {COUNTS_TABLE}
            WHERE COUNT_DATE = TO_DATE({count_date})
              AND STORE_ID = {store_id}
            """
        )

    session.write_pandas(
        df,
        table_name=COUNTS_TABLE,
        auto_create_table=False,
        overwrite=False,
    )
    return len(df)


def get_count_dates() -> list[str]:
    df = fetch_pandas(
        f"""
        SELECT DISTINCT COUNT_DATE
        FROM {COUNTS_TABLE}
        ORDER BY COUNT_DATE DESC
        """
    )
    return [str(v) for v in df["COUNT_DATE"].tolist()]


def get_stores(count_date: str) -> list[str]:
    count_date_lit = sql_literal(count_date)
    df = fetch_pandas(
        f"""
        SELECT DISTINCT STORE_ID
        FROM {COUNTS_TABLE}
        WHERE COUNT_DATE = TO_DATE({count_date_lit})
        ORDER BY STORE_ID
        """
    )
    return [str(v) for v in df["STORE_ID"].tolist()]


def get_diff_result(count_date: str, store_ids: Iterable[str] | None = None) -> pd.DataFrame:
    count_date_lit = sql_literal(count_date)

    store_filter = ""
    if store_ids:
        store_values = ", ".join(sql_literal(v) for v in store_ids)
        store_filter = f"AND inv.STORE_ID IN ({store_values})"

    return fetch_pandas(
        f"""
        SELECT
            inv.SNAPSHOT_DATE,
            cnt.COUNT_DATE,
            inv.STORE_ID,
            inv.PRODUCT_ID,
            inv.PRODUCT_NAME,
            inv.SYSTEM_STOCK_QTY,
            cnt.ACTUAL_STOCK_QTY,
            cnt.ACTUAL_STOCK_QTY - inv.SYSTEM_STOCK_QTY AS DIFF_QTY,
            CASE
                WHEN cnt.ACTUAL_STOCK_QTY IS NULL THEN '未棚卸'
                WHEN cnt.ACTUAL_STOCK_QTY = inv.SYSTEM_STOCK_QTY THEN '一致'
                ELSE '差異あり'
            END AS DIFF_STATUS
        FROM {INVENTORY_TABLE} inv
        LEFT JOIN {COUNTS_TABLE} cnt
          ON inv.SNAPSHOT_DATE = cnt.COUNT_DATE
         AND inv.STORE_ID = cnt.STORE_ID
         AND inv.PRODUCT_ID = cnt.PRODUCT_ID
        WHERE inv.SNAPSHOT_DATE = TO_DATE({count_date_lit})
        {store_filter}
        ORDER BY inv.STORE_ID, inv.PRODUCT_ID
        """
    )


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "diff_result") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


def show_summary(diff_df: pd.DataFrame) -> None:
    total_count = len(diff_df)
    diff_count = int((diff_df["DIFF_STATUS"] == "差異あり").sum())
    matched_count = int((diff_df["DIFF_STATUS"] == "一致").sum())
    missing_count = int((diff_df["DIFF_STATUS"] == "未棚卸").sum())

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("対象商品数", f"{total_count:,}")
    col2.metric("一致", f"{matched_count:,}")
    col3.metric("差異あり", f"{diff_count:,}")
    col4.metric("未棚卸", f"{missing_count:,}")


st.title(APP_TITLE)
st.caption("実棚卸ExcelをSnowflakeに登録し、理論在庫との差異を確認します。")

try:
    session = get_session()
except Exception as exc:
    st.error("Snowflakeへの接続に失敗しました。接続設定を確認してください。")
    st.exception(exc)
    st.stop()

upload_tab, diff_tab, download_tab = st.tabs(
    ["1. Excelアップロード", "2. 在庫差異確認", "3. Excelダウンロード"]
)

with upload_tab:
    st.subheader("実棚卸Excelアップロード")
    uploaded_file = st.file_uploader("実棚卸Excelを選択してください", type=["xlsx"])

    if uploaded_file is not None:
        try:
            raw_df = pd.read_excel(uploaded_file)
        except Exception as exc:
            st.error("Excelファイルの読み込みに失敗しました。")
            st.exception(exc)
            st.stop()

        st.write("アップロード内容プレビュー")
        st.dataframe(raw_df, use_container_width=True)

        validated_df, errors = validate_upload_df(raw_df)
        if errors:
            for error in errors:
                st.error(error)
        else:
            st.success("入力チェックに成功しました。")
            st.write("登録対象データ")
            st.dataframe(validated_df, use_container_width=True)

            if st.button("Snowflakeに登録する", type="primary"):
                with st.spinner("登録中..."):
                    inserted_count = replace_physical_counts(validated_df)
                st.success(f"{inserted_count:,}件の実棚卸データを登録しました。")

with diff_tab:
    st.subheader("在庫差異確認")

    count_dates = get_count_dates()
    if not count_dates:
        st.info("実棚卸データがまだ登録されていません。先にExcelをアップロードしてください。")
    else:
        selected_date = st.selectbox("棚卸日", count_dates)
        stores = get_stores(selected_date)
        selected_stores = st.multiselect("店舗ID", stores, default=stores)

        diff_df = get_diff_result(selected_date, selected_stores)
        show_summary(diff_df)

        only_diff = st.checkbox("差異ありのみ表示", value=False)
        display_df = diff_df[diff_df["DIFF_STATUS"] == "差異あり"] if only_diff else diff_df

        st.dataframe(display_df, use_container_width=True)

with download_tab:
    st.subheader("差異確認結果のExcelダウンロード")

    count_dates = get_count_dates()
    if not count_dates:
        st.info("ダウンロード対象のデータがありません。")
    else:
        selected_date = st.selectbox("棚卸日を選択", count_dates, key="download_date")
        stores = get_stores(selected_date)
        selected_stores = st.multiselect("店舗IDを選択", stores, default=stores, key="download_stores")

        diff_df = get_diff_result(selected_date, selected_stores)
        show_summary(diff_df)

        only_diff_download = st.checkbox("差異ありのみダウンロード", value=True)
        download_df = (
            diff_df[diff_df["DIFF_STATUS"] == "差異あり"]
            if only_diff_download
            else diff_df
        )

        st.dataframe(download_df, use_container_width=True)

        excel_bytes = dataframe_to_excel_bytes(download_df)
        st.download_button(
            label="Excelをダウンロード",
            data=excel_bytes,
            file_name=f"inventory_diff_{selected_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
