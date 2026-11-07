"""The old Faculty dashboard's address: the Organization admin portal replaced it, so anyone who
follows an old link or bookmark here is sent to views/org_admin.py. (Registered, hidden, in the
admin navigation only: a student or a visitor never reaches it.)"""

import streamlit as st

st.switch_page("views/org_admin.py")
