from glob import glob

from setuptools import find_packages, setup


package_name = "atlas_simulation"


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            [f"resource/{package_name}"],
        ),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/missions", glob("missions/*.json")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="ATLAS Team",
    maintainer_email="atlas@example.com",
    description="Core simulation engine package for the ATLAS project.",
    license="MIT",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            "atlas_demo_scenario = atlas_simulation.demo_scenario:main",
        ]
    },
)
