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
    include_package_data=True,
    install_requires=['numpy', 'pyserial'],
)
