CXX       = g++
CXXFLAGS  = -std=c++23 -O2 -Wall -Wextra \
			-I../include \
			-I/home/uniq/ns-3/build/include \
			-I/home/uniq/ns-3/src

LDFLAGS = -L/home/uniq/ns-3/build/lib \
		  -Wl,-rpath=/home/uniq/ns-3/build/lib \
		  -lns3.47-core \
		  -lns3.47-network \
		  -lns3.47-internet \
		  -lns3.47-applications \
		  -lns3.47-point-to-point \
		  -lns3.47-csma

SOURCES = $(wildcard src/*.cpp)
OBJECTS = $(patsubst src/%.cpp,build/%.o,$(SOURCES))
TARGET  = simulation

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJECTS)
	$(CXX) $(OBJECTS) $(LDFLAGS) -o $(TARGET)

build/%.o: src/%.cpp | build
	$(CXX) $(CXXFLAGS) -c $< -o $@

build:
	mkdir -p build

clean:
	rm -rf build $(TARGET)
