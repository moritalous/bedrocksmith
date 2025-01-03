import json
from datetime import datetime, timedelta, timezone

import streamlit as st
from streamlit_extras.tags import tagger_component

##########
# 定数定義
##########

# AWS Bedrockの呼び出しログを出力しているCloudWatchロググループ名とリージョン
default_log_group_name = "bedrock-invoke-logging-us-east-1"
default_region_name = "us-east-1"

##########


def split_event(message: str):
    """
    CloudWatchのログイベントメッセージを解析し、入力、出力、メタデータに分割する

    Args:
        message (str): JSON形式のログメッセージ

    Returns:
        tuple: (入力JSON, 出力JSON, メタデータ辞書)
    """
    event = json.loads(message)

    input_body_json = event["input"]["inputBodyJson"]
    output_body_json = event["output"]["outputBodyJson"]

    # メタデータを抽出
    metadata = {}
    metadata["timestamp"] = event["timestamp"]
    metadata["modelId"] = event["modelId"]
    metadata["operation"] = event["operation"]

    metadata["stopReason"] = output_body_json["stopReason"]
    metadata["usage"] = output_body_json["usage"]
    metadata["latencyMs"] = output_body_json["metrics"]["latencyMs"]

    # オプショナルな設定情報の抽出
    if "inferenceConfig" in input_body_json:
        metadata["inferenceConfig"] = input_body_json["inferenceConfig"]

    if "additionalModelRequestFields" in input_body_json:
        metadata["additionalModelRequestFields"] = input_body_json[
            "additionalModelRequestFields"
        ]

    return input_body_json, output_body_json, metadata


def write_tag(metadata: dict):
    """
    タグを表示

    Args:
        metadata (dict): メタデータを含む辞書
    """
    tagger_component(
        "",
        [
            f"🤖 {metadata['modelId']}",
            f"⌛️ {metadata['latencyMs']/1000} s",
            f"✏️ {metadata['usage']['totalTokens']}",
            f"✏️ {metadata['operation']}",
        ],
        ["BLUE", "GREEN", "ORANGE", "GRAY"],
    )


def write_system(body: dict):
    """
    システムメッセージを展開可能なコンポーネントとして表示

    Args:
        body (dict): システムメッセージを含む辞書
    """
    if "system" in body:
        system = input_body_json["system"]
        if len(system) == 0:
            return
        if "text" in system[0]:
            text = system[0]["text"]
            with st.expander("**SYSTEM**", expanded=False):
                st.write(text)


def write_input_message(body: dict):
    """
    入力メッセージを展開可能なコンポーネントとして表示

    Args:
        body (dict): 入力メッセージを含む辞書
    """
    messages = body["messages"]

    for message in messages:
        role = message["role"]
        content = message["content"]
        for c in content:
            if "text" in c:
                with st.expander(f"**{role.upper()}**", expanded=True):
                    st.text(c["text"])


def write_output_message(body: dict):
    """
    出力メッセージを展開可能なコンポーネントとして表示

    Args:
        body (dict): 出力メッセージを含む辞書
    """
    output = body["output"]
    message = output["message"]
    role = message["role"]
    content = message["content"]
    for c in content:
        if "text" in c:
            with st.expander(f"**{role.upper()}**", expanded=True):
                st.text(c["text"])


# ページ設定
st.set_page_config(layout="wide")
st.title("BedrockSmith")

# ログ取得期間の選択肢を定義
time_range = {
    "1時間": 1,
    "6時間": 6,
    "12時間": 12,
    "24時間": 24,
    "48時間": 48,
    "96時間": 96,
}

## サイドバーの設定項目
with st.sidebar:
    with st.expander("設定", expanded=True):
        # ログ取得のパラメータ設定
        log_group_name = st.text_input(
            "ロググループ名", value="bedrock-invoke-logging-us-east-1"
        )
        region_name = st.text_input("リージョン名", value=default_region_name)
        select_range = st.selectbox("取得期間", time_range.keys(), index=3)
        limit = st.slider("取得件数", min_value=1, max_value=1000, value=100, step=10)
    submit = st.button("ログ取得")

## ログ取得の実行
if submit:
    # 表示対象があれば一旦削除
    if "event" in st.session_state:
        del st.session_state["event"]

    # 時間範囲の計算
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=time_range[select_range])
    start_time_ms = int(start_time.timestamp() * 1000)

    # AWS CloudWatch Logsからログを取得
    import boto3

    client_logs = boto3.client("logs", region_name=region_name)

    # 最新のログストリームを取得
    response = client_logs.describe_log_streams(
        logGroupIdentifier=log_group_name, orderBy="LastEventTime", descending=True
    )

    # 指定された条件でログイベントをフィルタリング
    log_stream_name = response["logStreams"][0]["logStreamName"]
    response = client_logs.filter_log_events(
        logGroupName=log_group_name,
        logStreamNames=[log_stream_name],
        startTime=start_time_ms,
        filterPattern='{($.operation = "Converse") || ($.operation = "ConverseStream")}',
        limit=limit,
    )

    # タイムスタンプでソート
    sorted_events = sorted(
        response["events"], key=lambda x: x["timestamp"], reverse=True
    )

    st.session_state.events = sorted_events

## サイドバーにログイベントの一覧を表示
if "events" in st.session_state:
    events = st.session_state.events

    with st.sidebar:
        for event in events:
            input_body_json, output_body_json, metadata = split_event(event["message"])

            with st.container(border=True):
                # イベントの概要をタグとして表示
                write_tag(metadata)
                st.write(metadata["timestamp"])

                # イベントの詳細表示用ボタン
                def show_click(event):
                    st.session_state.event = event

                st.button(
                    "Show",
                    key=event["eventId"],
                    on_click=show_click,
                    kwargs={"event": event},
                )

    # 初期表示として最新のイベントを選択
    if "event" not in st.session_state and len(events) > 0:
        st.session_state.event = events[0]

## メインエリアにイベントの詳細を表示
if "event" in st.session_state:
    event = st.session_state.event
    input_body_json, output_body_json, metadata = split_event(event["message"])

    # イベントの概要をタグとして表示
    write_tag(metadata)

    # 3カラムレイアウトで詳細情報を表示
    c1, c2, c3 = st.columns(3)

    # 入力情報の表示
    with c1:
        st.subheader("Input", divider=True)
        t1, t2 = st.tabs(["Text", "Raw"])
        with t1:
            write_system(input_body_json)
            write_input_message(input_body_json)
        with t2:
            st.write(input_body_json)

    # 出力情報の表示
    with c2:
        st.subheader("Output", divider=True)
        t1, t2 = st.tabs(["Text", "Raw"])
        with t1:
            write_output_message(output_body_json)
        with t2:
            st.write(output_body_json)

    # メタデータの表示
    with c3:
        st.subheader("Metadata", divider=True)
        # メタデータの種類に応じて表示形式を変える
        for k, v in metadata.items():
            if type(v) == dict:
                with st.container(border=True):
                    st.text(k)
                    for kk, vv in v.items():
                        st.caption(kk)
                        st.text(vv)
            if type(v) == str:
                with st.container(border=True):
                    st.caption(k)
                    st.text(v)
