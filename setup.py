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
    install_requires=['dash==1.14.0', 'dash-bootstrap-components==0.10.4', 'matplotlib==3.2.2', 'numpy==1.19.1', 'pyserial'],
)
