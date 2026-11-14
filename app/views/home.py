"""Home page: what the tool does and how to start."""

import streamlit as st

st.header("Which crop rotation suits your field?")
st.write(
    "Pick a field in Iowa, tell us about your farm and what matters most to you, and Field Shift "
    "compares crop rotations on that field over more than 40 years of real weather."
)

st.page_link("views/analyse.py", label="Analyse a field", icon=":material/arrow_forward:")

st.subheader("How it works")
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("**1. Pick your field**  \n"
                "Click it on the map. We look up its soil (USDA soil survey), slope (USDA survey, "
                "checked with NASA SRTM elevation) and the crops grown there since 2008 (USDA crop maps).")
with c2:
    st.markdown("**2. Tell us about your farm**  \n"
                "Hay buyer? Equipment for cover crops? Open to new crops? Then set what matters to you: "
                "drought, water quality, soil and erosion, income, pests.")
with c3:
    st.markdown("**3. Compare rotations**  \n"
                "Each rotation runs through a daily soil-water model with NASA POWER weather since 1984, "
                "and is scored against what you grow now - with a range, not just one number.")

st.subheader("What it is - and what it is not")
st.markdown(
    "- A way to **compare options on the same weather and soil**, using published research where "
    "measurements do not exist.\n"
    "- **Not** a yield or profit forecast, and **not** a replacement for your own judgement or your "
    "agronomist. Every number links back to where it came from (see the Evidence tab and the About page)."
)

st.caption("Built for the NASA Space Apps Challenge 2026: Field Shift - Adapting Farms with NASA Data.")
