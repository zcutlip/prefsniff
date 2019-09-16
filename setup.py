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
          'console_scripts': ['prefsniff=prefsniff.prefsniff_main:main'], },
      python_requires='>= 2.7, != 3.0.*, != 3.1.*, != 3.2.*, != 3.3.*, != 3.4.*, != 3.5.*, != 3.6.*,',
      install_requires=['watchdog>=0.8.3'],
      )
