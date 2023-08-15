from setuptools import setup


setup(
    name='Eisenbahn_App',
    version='1.0.0',
    packages=['fpme'],
    description='Modelleisenbahn-App für das Ferienprogramm',
    license='MIT',
    author='Philipp Holl',
    author_email='philipp@mholl.de',
    url='https://github.com/holl-/TrainControl',
    include_package_data=False,
    install_requires=['dash', 'dash-bootstrap-components', 'dash-daq', 'numpy', 'pyserial', 'win-raw-in'],
)
