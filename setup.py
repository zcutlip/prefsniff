from setuptools import setup
about = {}
with open("prefsniff/__about__.py") as fp:
    exec(fp.read(), about)

setup(name=about["__title__"],
      version=about["__version__"],
      description=about["__summary__"],
      url="https://github.com/zcutlip/prefsniff",
      packages=['prefsniff'],
      entry_points={
          'console_scripts': ['prefsniff=prefsniff.prefsniff_main:main'], },
      python_requires='>=2.7,>=3.7',
      install_requires=['watchdog>=0.8.3'],
      )
