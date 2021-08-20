import plotly.graph_objects as go


# https://plotly.com/python/gauge-charts/
# https://plotly.com/python/animations/

# fig = go.Figure(
#     data=go.Indicator(mode="gauge+number", value=270, domain={'x': [0, 1], 'y': [0, 1]}, title={'text': "Speed"})
# )
# fig.show()


fig = go.Figure(
    data=go.Indicator(mode="gauge+number", value=270, domain={'x': [0, .5], 'y': [0, .5]}, title={'text': "Dampflok ▶"}, number={'suffix': " km/h"}),
    # data=[go.Scatter(x=[0, 1], y=[0, 1])],
    layout=go.Layout(
        xaxis=dict(range=[0, 5], autorange=False),
        yaxis=dict(range=[0, 5], autorange=False),
        title="Start Title",
        updatemenus=[dict(
            type="buttons",
            buttons=[dict(label="Play",
                          method="animate",
                          args=[None])])]
    ),
    frames=[go.Frame(data=go.Indicator(mode="gauge+number", value=50, domain={'x': [0, 1], 'y': [0, 1]}, title={'text': "Speed"})),
            go.Frame(data=go.Indicator(mode="gauge+number", value=300, domain={'x': [0, 1], 'y': [0, 1]}, title={'text': "Speed"})),
            go.Frame(data=go.Indicator(mode="gauge+number", value=0, domain={'x': [0, 1], 'y': [0, 1]}, title={'text': "Speed"}), layout=go.Layout(title_text="End Title"))]
)

fig.show()
