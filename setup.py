from setuptools import find_packages, setup

from strongarm import __version__

setup(
    name="strongarm-ios",
    version=__version__,
    description="Mach-O/ARM64 analyzer",
    author="Data Theorem",
    url="https://github.com/datatheorem/strongarm",
    packages=find_packages(exclude=["tests"]),
    install_requires=["capstone", "more_itertools", "strongarm_dataflow==2.1.2"],
    package_data={"strongarm": ["py.typed"]},
    data_files=[("", ["LICENSE.txt"])],
)
