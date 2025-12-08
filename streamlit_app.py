import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials


# ---------------------- CONFIG ----------------------

# Logins:
# - doctor / password123 => New Entry + Mapping
# - admin  / doctor      => New Entry + Previous Entries + Mapping
VALID_USERS = {
    "doctor": {"password": "password123", "role": "doctor"},
    "admin": {"password": "doctor", "role": "admin"},
}

# Columns for the main data entry table
COLUMNS = ["col1", "col2", "col3", "col4"]

DEFAULT_ROWS = 10
TIMEZONE = "Asia/Kolkata"

# Excel file with the specialty mapping reference
EXCEL_FILE = "Specialty Mapping.xlsx"   # must be present in the app repo root


# ---------------------- GOOGLE SHEETS HELPERS ----------------------

@st.cache_resource
def get_gspread_client():
    service_info = dict(st.secrets["gcp_service_account"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(service_info, scopes=scopes)
    return gspread.authorize(creds)


def get_spreadsheet():
    client = get_gspread_client()
    spreadsheet_id = st.secrets["SPREADSHEET_ID"]
    return client.open_by_key(spreadsheet_id)


def get_today_sheet():
    """Get or create today's worksheet for main data: data_YYYY-MM-DD."""
    sh = get_spreadsheet()
    now = datetime.now(ZoneInfo(TIMEZONE))
    sheet_name = f"data_{now.strftime('%Y-%m-%d')}"

    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows="2000", cols=str(len(COLUMNS)))
        ws.append_row(COLUMNS)

    return ws


def append_rows(ws, df: pd.DataFrame) -> int:
    """Append non-empty rows from df to worksheet."""
    # Treat everything as text when saving main data
    df_clean = df.dropna(how="all")
    if df_clean.empty:
        return 0

    df_clean = df_clean.fillna("").astype(str)
    rows = df_clean.values.tolist()

    for r in rows:
        ws.append_row(r, value_input_option="USER_ENTERED")
    return len(df_clean)


def get_date_sheets():
    """Return list of (date_str, worksheet) sorted by date descending for main data."""
    sh = get_spreadsheet()
    worksheets = sh.worksheets()

    date_sheets = []
    for ws in worksheets:
        if ws.title.startswith("data_"):
            date_str = ws.title.replace("data_", "", 1)
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                date_sheets.append((d, date_str, ws))
            except ValueError:
                continue

    date_sheets.sort(key=lambda x: x[0], reverse=True)
    return [(date_str, ws) for (_, date_str, ws) in date_sheets]


def get_mapping_sheet_for_today():
    """
    Get or create today's worksheet for specialty mapping:
    mapping_YYYY-MM-DD
    All submissions on the same day go into this sheet.
    """
    sh = get_spreadsheet()
    now = datetime.now(ZoneInfo(TIMEZONE))
    sheet_name = f"mapping_{now.strftime('%Y-%m-%d')}"

    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        # 2000 rows, 50 columns (adjust if your grid is larger)
        ws = sh.add_worksheet(title=sheet_name, rows="2000", cols="50")
    return ws


# ---------------------- EXCEL / SPECIALTY MAPPING HELPERS ----------------------

@st.cache_data
def load_reference_sheet():
    """
    Load Specialty Mapping.xlsx and cache it.
    Everything is treated as text; NaNs become empty strings.
    """
    try:
        # Read as strings; header row is the first row in Excel
        df = pd.read_excel(EXCEL_FILE, dtype=str)
        if df is None or df.empty:
            return None
        df = df.fillna("")
        return df
    except Exception as e:
        st.error(f"Failed to load Excel file '{EXCEL_FILE}': {e}")
        return None


# ---------------------- LOGIN ----------------------

def login_page():
    st.title("Secure Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        user = VALID_USERS.get(username)
        if user and user["password"] == password:
            st.session_state["logged_in"] = True
            st.session_state["user_role"] = user["role"]
            st.rerun()
        else:
            st.error("Invalid username or password")


# ---------------------- PREVIOUS ENTRIES (ADMIN ONLY) ----------------------

def history_tab():
    st.subheader("Previous Entries")

    # Make table hard to copy from (not bullet-proof)
    st.markdown(
        """
        <style>
        .no-select-table, .no-select-table * {
            -webkit-user-select: none !important;
            -moz-user-select: none !important;
            -ms-user-select: none !important;
            user-select: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    date_sheets = get_date_sheets()
    if not date_sheets:
        st.write("No previous data yet.")
        return

    date_options = ["None"] + [d for (d, _) in date_sheets]
    selected = st.selectbox("Select a date to view:", date_options, index=0)

    if selected == "None":
        st.info("Select a date above to view previous submissions.")
        return

    ws = next((w for d, w in date_sheets if d == selected), None)
    if ws is None:
        st.write("No data for this date.")
        return

    rows = ws.get_all_values()
    if not rows or len(rows) <= 1:
        st.write("No rows submitted for this date.")
        return

    header = rows[0]
    data_rows = rows[1:]
    df = pd.DataFrame(data_rows, columns=header)

    st.markdown(f"Showing data for **{selected}**:")
    html_table = df.to_html(index=False, escape=True)
    st.markdown(f'<div class="no-select-table">{html_table}</div>', unsafe_allow_html=True)
    st.caption("This view is read-only; text selection is disabled in the UI.")


# ---------------------- NEW ENTRY TAB ----------------------

def blank_df():
    return pd.DataFrame(
        [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)],
        columns=COLUMNS,
    )


def new_entry_tab():
    st.subheader("New Data Entry")

    st.write(
        "Enter rows below. After you click **Submit**, the table is cleared. "
    )

    # Hide widget toolbar (CSV/download)
    st.markdown(
        """
        <style>
        [data-testid="stElementToolbar"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Use a dynamic key to reset the editor on demand
    if "editor_key" not in st.session_state:
        st.session_state["editor_key"] = "editor_1"

    editor_key = st.session_state["editor_key"]

    # Always start with blank df for a new key; for an existing key,
    # Streamlit will keep the internal value as the user edits.
    df_default = blank_df()

    edited = st.data_editor(
        df_default,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key=editor_key,
    )

    col1, col2 = st.columns(2)
    with col1:
        submit = st.button("Submit to Google Sheet", type="primary")
    with col2:
        clear = st.button("Clear Table")

    if clear:
        # Change the key so the widget is recreated with a fresh blank table
        st.session_state["editor_key"] = f"editor_reset_{datetime.now().timestamp()}"
        st.rerun()

    if submit:
        try:
            ws = get_today_sheet()
            saved_rows = append_rows(ws, edited)
            if saved_rows == 0:
                st.warning("No non-empty rows to save.")
            else:
                st.success(f"Saved {saved_rows} rows to today's sheet.")
                # Change key to reset editor to blank
                st.session_state["editor_key"] = f"editor_reset_{datetime.now().timestamp()}"
                st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ---------------------- SPECIALTY MAPPING SECTION ----------------------

def mapping_editor_section(role: str):
    """
    Homepage section: show & edit Specialty Mapping.xlsx.

    Requirements:
    - First 2 columns from Excel (and the first row in that Excel file) are "frozen" and constant.
    - Adjacent cells (beyond the first 2 columns) are editable.
    - On submit:
        * Entire grid (first 2 cols from Excel + edited cells) is saved
          to mapping_YYYY-MM-DD in the same Google Sheet.
        * The editable part on the website is reset back to the original template.
    """

    st.subheader("Specialty Mapping – Scenario Grid")

    df_ref = load_reference_sheet()
    if df_ref is None:
        st.info("Reference sheet not available or could not be loaded.")
        return

    # Make sure everything is string, no NaNs
    df_ref = df_ref.fillna("").astype(str)

    # First 2 columns are the "frozen" reference
    if df_ref.shape[1] < 3:
        st.error("Specialty Mapping.xlsx must have at least 3 columns.")
        return

    frozen_part = df_ref.iloc[:, :2]         # first 2 columns
    editable_part_default = df_ref.iloc[:, 2:]  # all remaining columns

    editable_cols = list(editable_part_default.columns)

    st.markdown(
        """
        - **Left side**: Fixed reference from Excel (first two columns; first row included).  
        - **Right side**: Editable cells for each scenario/field (all other columns).  
        - Click **Submit Specialty Mapping** to save the full grid for today's date
          and reset the inputs.
        """
    )

    # Keep editable data in session_state
    if "mapping_edit_df" not in st.session_state:
        st.session_state["mapping_edit_df"] = editable_part_default.copy()

    if "mapping_editor_key" not in st.session_state:
        st.session_state["mapping_editor_key"] = "mapping_1"

    current_edit_df = st.session_state["mapping_edit_df"]
    # Ensure strict string type
    current_edit_df = current_edit_df.fillna("").astype(str)

    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.markdown("**Reference (fixed)**")
        st.dataframe(
            frozen_part,
            use_container_width=True,
            hide_index=False,
        )

    with col_right:
        st.markdown("**Fill / Edit mapping cells**")

        column_config = {
            col: st.column_config.TextColumn()
            for col in editable_cols
        }

        edited = st.data_editor(
            current_edit_df,
            num_rows="fixed",           # same number of rows as reference
            hide_index=False,
            use_container_width=True,
            column_config=column_config,
            key=st.session_state["mapping_editor_key"],
        )

        # Always keep in text form
        edited = edited.fillna("").astype(str)
        st.session_state["mapping_edit_df"] = edited

    # Submit button
    if st.button("Submit Specialty Mapping", type="primary"):
        try:
            ws = get_mapping_sheet_for_today()

            # Reconstruct full DataFrame: first 2 cols from reference + edited scenario cols
            full_df = pd.concat(
                [frozen_part.reset_index(drop=True),
                 edited.reset_index(drop=True)],
                axis=1,
            )

            full_df = full_df.fillna("").astype(str)

            # Prepare header and values as plain strings (no NaN)
            header = ["" if (h is None or str(h) == "nan") else str(h) for h in full_df.columns]
            values = full_df.values.tolist()

            # Ensure all inner cells are plain Python strings
            clean_values = []
            for row in values:
                clean_row = []
                for v in row:
                    if v is None:
                        clean_row.append("")
                    else:
                        v_str = str(v)
                        if v_str == "nan":
                            v_str = ""
                        clean_row.append(v_str)
                clean_values.append(clean_row)

            ws.clear()
            ws.update("A1", [header] + clean_values)

            st.success(
                "Specialty Mapping saved to Google Sheets "
                f"(sheet: '{ws.title}')."
            )

            # Reset editable part back to the original template (i.e., Excel's content)
            st.session_state["mapping_edit_df"] = editable_part_default.copy()
            st.session_state["mapping_editor_key"] = f"mapping_{datetime.now().timestamp()}"

            st.rerun()

        except Exception as e:
            st.error(f"Error saving mapping to Google Sheets: {e}")


# ---------------------- MAIN ----------------------

def main():
    st.set_page_config(page_title="Doctor Input Portal", layout="wide")

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["user_role"] = None

    if not st.session_state["logged_in"]:
        login_page()
        return

    role = st.session_state.get("user_role", "doctor")

    with st.sidebar:
        st.write(f"Logged in as: **{role}**")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

    st.title("Doctor Input Portal")

    # --- Specialty Mapping section on homepage ---
    mapping_editor_section(role)

    st.markdown("---")

    # --- Main data entry / history tabs ---
    if role == "admin":
        tab1, tab2 = st.tabs(["New Entry", "Previous Entries"])
        with tab1:
            new_entry_tab()
        with tab2:
            history_tab()
    else:
        (tab1,) = st.tabs(["New Entry"])
        with tab1:
            new_entry_tab()


if __name__ == "__main__":
    main()
