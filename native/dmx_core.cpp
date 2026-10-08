#include <algorithm>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <vector>

#if defined(_WIN32)
#define LUMENDESK_EXPORT __declspec(dllexport)
#else
#define LUMENDESK_EXPORT __attribute__((visibility("default")))
#endif

namespace {
constexpr std::size_t kChannelsPerUniverse = 512;
constexpr int kMaximumUniverses = 63999;
std::mutex g_mutex;
std::vector<std::uint8_t> g_data;
int g_universes = 0;

bool valid_universe(int universe) {
    return universe >= 0 && universe < g_universes;
}
}

extern "C" {
LUMENDESK_EXPORT int dmx_initialize(int universes) {
    if (universes < 1 || universes > kMaximumUniverses) {
        return 0;
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    g_universes = universes;
    g_data.assign(static_cast<std::size_t>(universes) * kChannelsPerUniverse, 0);
    return 1;
}

LUMENDESK_EXPORT void dmx_set_channel(int universe, int channel, int value) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (!valid_universe(universe) || channel < 0 ||
        channel >= static_cast<int>(kChannelsPerUniverse)) {
        return;
    }
    const auto offset = static_cast<std::size_t>(universe) * kChannelsPerUniverse +
                        static_cast<std::size_t>(channel);
    g_data[offset] = static_cast<std::uint8_t>(std::clamp(value, 0, 255));
}

LUMENDESK_EXPORT int dmx_get_channel(int universe, int channel) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (!valid_universe(universe) || channel < 0 ||
        channel >= static_cast<int>(kChannelsPerUniverse)) {
        return 0;
    }
    const auto offset = static_cast<std::size_t>(universe) * kChannelsPerUniverse +
                        static_cast<std::size_t>(channel);
    return g_data[offset];
}

LUMENDESK_EXPORT int dmx_copy_universe(int universe, std::uint8_t* destination,
                                       int destination_size) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (!valid_universe(universe) || destination == nullptr ||
        destination_size < static_cast<int>(kChannelsPerUniverse)) {
        return 0;
    }
    const auto offset = static_cast<std::size_t>(universe) * kChannelsPerUniverse;
    std::copy_n(g_data.begin() + static_cast<std::ptrdiff_t>(offset),
                kChannelsPerUniverse, destination);
    return static_cast<int>(kChannelsPerUniverse);
}

LUMENDESK_EXPORT int dmx_effect_value(int effect, int position, int count,
                                      double elapsed_seconds, double speed,
                                      int intensity) {
    if (count <= 0 || position < 0 || position >= count) {
        return 0;
    }
    constexpr double kPi = 3.14159265358979323846;
    const double spatial = static_cast<double>(position) / count;
    const double phase = elapsed_seconds * std::max(0.0, speed);
    double level = 0.0;
    switch (effect) {
    case 0: // Pulse
        level = 0.5 + 0.5 * std::sin(2.0 * kPi * phase);
        break;
    case 1: { // Chase
        double progress = std::fmod(spatial - phase, 1.0);
        if (progress < 0.0) progress += 1.0;
        level = progress < 0.18 ? 1.0 : 0.0;
        break;
    }
    case 2: // Wave
        level = 0.5 + 0.5 * std::sin(2.0 * kPi * (spatial + phase));
        break;
    case 3: // Strobe
        level = std::fmod(phase, 1.0) < 0.5 ? 1.0 : 0.0;
        break;
    case 4: // Sine
        level = 0.5 + 0.5 * std::sin(2.0 * kPi * phase + spatial * kPi);
        break;
    default:
        return 0;
    }
    const int bounded_intensity = std::clamp(intensity, 0, 255);
    return static_cast<int>(std::lround(level * bounded_intensity));
}
}
