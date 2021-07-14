import os
from setuptools import setup, find_packages


def parse_requirements(file):
    return sorted(set(
        line.partition('#')[0].strip()
        for line in open(os.path.join(os.path.dirname(__file__), file))
    )
                  -set('')
                  )


setup(
    name='seplanet',
    packages=find_packages(),
    include_package_data=True,
    version='0.4',
    description='High-level functionality for the inventory, download '
                'and pre-processing of Planet data',
    install_requires=parse_requirements('requirements.txt'),
    url='https://github.com/BuddyVolly/seplanet',
    author='Andreas Vollrath',
    author_email='andreas.vollrath[at]fao.org',
    license='MIT License',
    keywords=['Planet', 'Remote Sensing', 'Earth Observation',
              'Sepal'],
    zip_safe=False #,
    #setup_requires=['pytest-runner'],
    #tests_require=['pytest']
)