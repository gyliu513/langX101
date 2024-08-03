import streamlit as st

with st.form(key='my_form'):
    name = st.text_input('Enter your name')
    age = st.number_input('Enter your age', min_value=1, max_value=100)
    submit_button = st.form_submit_button(label='Submit')

if submit_button:
    st.write(f'Hello, {name}! You are {age} years old.')