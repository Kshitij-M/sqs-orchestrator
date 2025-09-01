try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

version = "0.1.2"
setup(
    name="sqs-orchestrator",
    version=version,
    author="Kshitij Mohan",
    author_email="kshitijmhn@gmail.com",
    description=(""),
    license="BSD",
    packages=["sqs_orchestrator"],
    install_requires=['boto3', 'multiprocessing-logging'],
)