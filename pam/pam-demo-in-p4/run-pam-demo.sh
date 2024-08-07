P4APPRUNNER=./utils/p4apprunner.py
APPNAME=multicast.p4app
mkdir -p build/
sudo rm -rf build/*
#sudo mn -c
cd $APPNAME
tar -czf ../build/$APPNAME.tgz * --exclude='build'
cd -
#cd build
sudo python $P4APPRUNNER $APPNAME.tgz --build-dir ./build