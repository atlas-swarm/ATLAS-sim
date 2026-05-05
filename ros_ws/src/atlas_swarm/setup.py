from setuptools import find_packages, setup

package_name = "atlas_swarm"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="zeynepselcuk03",
    maintainer_email="zeynep.selcuk03@gmail.com",
    description="SwarmCoordinator, FormationManager, and swarm messaging models for the ATLAS project.",
    license="MIT",
    extras_require={"test": ["pytest"]},
    entry_points={"console_scripts": []},
)
