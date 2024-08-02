import streamlit as st
import pandas as pd
import numpy as np

st.title('Simple Streamlit App')

st.write("Here's our first attempt at using Streamlit:")
st.write(pd.DataFrame({
    'Column A': [1, 2, 3, 4],
    'Column B': [10, 20, 30, 40]
}))

st.write("A random chart:")
chart_data = pd.DataFrame(
    np.random.randn(20, 3),
    columns=['a', 'b', 'c']
)

st.line_chart(chart_data)