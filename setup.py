from setuptools import setup

about = {}
with open("README.md", "r") as fh:
    long_description = fh.read()

with open("prefsniff/__about__.py") as fp:
    exec(fp.read(), about)

setup(name=about["__title__"],
      version=about["__version__"],
      description=about["__summary__"],
      long_description=long_description,
      long_description_content_type="text/markdown",
      url="https://github.com/zcutlip/prefsniff",
      packages=['prefsniff'],
      entry_points={
          'console_scripts': ['prefsniff=prefsniff.prefsniff:main'], },
      python_requires='>= 3.7',
      install_requires=['watchdog>=1.0.2', 'py-dict-repr'],
      )
