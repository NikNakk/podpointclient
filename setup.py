from setuptools import setup, find_packages

with open('podpointclient/version.py') as fh:  exec(fh.read())
with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    # The distribution name is distinct from the import package. Users install
    # podpointclient-niknakk and continue to ``import podpointclient``.
    name="podpointclient-niknakk",
    version=__version__,
    author="Matthew Rayner",
    author_email="hello@rayner.io",
    maintainer="Nick Kennedy",
    description="A domain-level and endpoint-specific client for Pod Point home chargers",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/NikNakk/podpointclient",
    project_urls={
        "Source": "https://github.com/NikNakk/podpointclient",
        "Bug Tracker": "https://github.com/NikNakk/podpointclient/issues",
        "Upstream": "https://github.com/mattrayner/podpointclient",
    },
    license="MIT",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    packages=find_packages(exclude=['tests']),
    install_requires=[
        "aiohttp>=3",
        'async-timeout>=4; python_version < "3.11"',
        "StrEnum>=0.4,<0.5",
        "pytz",
    ],
    python_requires=">=3.7",
    keywords='Pod Point PodPoint EV charger',
    include_package_data=True,
)
