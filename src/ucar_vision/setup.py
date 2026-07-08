from setuptools import find_packages, setup
from glob import glob
import os

package_name = 'ucar_vision'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='sunrise',
    maintainer_email='sunrise@todo.todo',
    description='RDK X5 stereo vision monitoring: fall detection + fire detection + alarm',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'vision_monitor = ucar_vision.vision_monitor:main',
            'alarm_controller = ucar_vision.alarm_controller:main',
            'person_detector = ucar_vision.person_detector:main',
        ],
    },
)
