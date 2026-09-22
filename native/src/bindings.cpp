#include <cmath>
#include <cstdint>
#include <stdexcept>

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

namespace py = pybind11;

double mean_abs_diff(
    py::array_t<std::uint8_t, py::array::c_style | py::array::forcecast> a,
    py::array_t<std::uint8_t, py::array::c_style | py::array::forcecast> b
) {
    auto buf_a = a.request();
    auto buf_b = b.request();

    if (buf_a.size != buf_b.size) {
        throw std::runtime_error("Input arrays must have the same number of elements");
    }

    const auto* pa = static_cast<const std::uint8_t*>(buf_a.ptr);
    const auto* pb = static_cast<const std::uint8_t*>(buf_b.ptr);

    if (buf_a.size == 0) {
        return 0.0;
    }

    std::uint64_t sum = 0;
    for (py::ssize_t i = 0; i < buf_a.size; ++i) {
        sum += static_cast<std::uint64_t>(
            std::abs(static_cast<int>(pa[i]) - static_cast<int>(pb[i]))
        );
    }

    return static_cast<double>(sum) / static_cast<double>(buf_a.size);
}

PYBIND11_MODULE(fast_core, m) {
    m.doc() = "Optional C++ acceleration for Frame Sorter";
    m.def("mean_abs_diff", &mean_abs_diff, "Mean absolute pixel difference");
}
