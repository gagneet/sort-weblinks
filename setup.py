from setuptools import setup, find_packages

setup(
    name="weblinks_organizer",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "aiohttp",
        "beautifulsoup4",
        "tqdm",
        "pyyaml",
    ],
    entry_points={
        "console_scripts": [
            "weblinks-organizer=weblinks_organizer.main:main",
        ],
    },
)