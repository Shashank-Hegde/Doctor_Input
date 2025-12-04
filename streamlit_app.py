import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials


# ---------------------- CONFIG ----------------------

# Allowed logins
VALID_USERS = {
    "engineer1": "password123",
    "engineer2": "mypassword",
}

# Data entry columns
COLUMNS = ["col1", "col2", "col3", "col4"]

# Blank rows shown to engineer
DEFAULT_ROWS = 10

TIMEZONE = "Asia/Kolkata"


# ---------------------- HELPERS ----------------------

@st.cache_resource
def get_gspread_client():
    """Create a cached gspread client."""
    service_info = dict(st.secrets["gcp_service_account"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(service_info, scopes=scopes)
    return gspread.authorize(creds)


def get_today_sheet():
    spreadsheet_id = st.secrets["SPREADSHEET_ID"]
    client = get_gspread_client()
    sh = client.open_by_key(spreadsheet_id)

    now = datetime.now(ZoneInfo(TIMEZONE))
    sheet_name = f"data_{now.strftime('%Y-%m-%d')}"

    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows="2000", cols=str(len(COLUMNS)))
        ws.append_row(COLUMNS)

    return ws


def append_rows(ws, df):
    df_clean = df.dropna(how="all")
    if df_clean.empty:
        return 0

    rows = df_clean.values.tolist()
    for r in rows:
        ws.append_row(r, value_input_option="USER_ENTERED")
    return len(rows)


# ---------------------- LOGIN PAGE ----------------------

def login_page():
    st.title("Secure Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    login_btn = st.button("Login")

    if login_btn:
        if username in VALID_USERS and VALID_USERS[username] == password:
            st.session_state["logged_in"] = True
            st.experimental_rerun()
        else:
            st.error("Invalid username or password")


# ---------------------- MAIN APP ----------------------

def entry_page():
    st.title("Secure Data Entry (Write-Only)")

    st.write("Enter rows below. Submitted data cannot be viewed again.")

    if "input_df" not in st.session_state:
        st.session_state["input_df"] = pd.DataFrame(
            [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)],
            columns=COLUMNS,
        )

    edited = st.data_editor(
        st.session_state["input_df"],
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        submit = st.button("Submit to Google Sheet", type="primary")

    with col2:
        clear = st.button("Clear Table")

    if clear:
        st.session_state["input_df"] = pd.DataFrame(
            [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)], columns=COLUMNS
        )
        st.experimental_rerun()

    if submit:
        try:
            ws = get_today_sheet()
            saved_rows = append_rows(ws, edited)

            if saved_rows == 0:
                st.warning("No non-empty rows to save.")
            else:
                st.success(f"Saved {saved_rows} rows to today's sheet.")

                st.session_state["input_df"] = pd.DataFrame(
                    [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)],
                    columns=COLUMNS,
                )
                st.experimental_rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ---------------------- ROUTER ----------------------

def main():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        login_page()
    else:
        entry_page()


if __name__ == "__main__":
    main()
