"""About page: challenge, data, method, limits and team."""

import streamlit as st

import ui


def render():
    ui.page_header("About", "About Orbital Acre",
                   "Where the numbers come from, how they are used, and what the tool cannot know.")

    ui.section_heading("The challenge")
    st.write("Orbital Acre is our answer to the NASA Space Apps Challenge 2026 - *Field Shift: Adapting Farms "
             "with NASA Data* - built for the Lincoln local event. It helps a farmer explore crop-rotation "
             "options that build soil health and cope with a changing climate, one field at a time, in Iowa.")

    ui.section_heading("Data")
    st.markdown(
        "| Data | Source | Used for |\n"
        "|---|---|---|\n"
        "| Daily weather since 1981 | **NASA POWER** | Water model, drought, drainage, erosion days, climate trends |\n"
        "| Elevation | **NASA SRTM** | Checking the field's slope |\n"
        "| Soil moisture | **NASA SMAP** (via NASA AppEEARS) | Checking the water model |\n"
        "| Field greenness | **NASA HLS** - Landsat and Sentinel-2 (via AppEEARS) | Checking the crop calendar |\n"
        "| Soils | USDA NRCS SSURGO (Soil Data Access) | Water-holding capacity, drainage, slope |\n"
        "| Past crops | USDA NASS Cropland Data Layer | The field's current rotation |\n"
        "| Ground checks | ISU Soil Moisture Network, NWS station Ames 5 SE (Iowa Environmental Mesonet) | Validation |\n"
        "| Costs, yields, prices | Iowa State University budgets, USDA NASS, USDA WASDE | Income |\n"
        "| Rotation effects | Marsden Farm trial (Davis et al. 2012) and Iowa State Extension | Scores and income |"
    )

    ui.section_heading("Limits")
    st.markdown(
        "- Weather is a ~50 km average, not your rain gauge; soil and crop maps can be wrong for a given field.\n"
        "- Income uses typical yields, prices and costs - it compares rotations, it does not forecast profit.\n"
        "- Several values are starting points from published research and are marked for expert review."
    )

    ui.section_heading("Team", sub="A&L Orbital")
    st.html('<div class="fs-team">'
            '<div class="m"><span class="av">A</span><div><b>Adam</b><span>Age 21</span></div></div>'
            '<div class="m"><span class="av">L</span><div><b>Leo</b><span>Age 21</span></div></div>'
            '</div>'
            '<p class="fs-source">NASA Space Apps Challenge 2026 · Lincoln local event · '
            'Challenge: Field Shift - Adapting Farms with NASA Data.</p>')

    st.caption("AI use: parts of the code and text were drafted with Claude (Anthropic) and reviewed by the team.")
