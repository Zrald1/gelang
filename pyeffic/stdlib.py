"""GE Standard Library

This module provides GE runtime helper functions that are emitted as
backend-specific runtime code. These are NOT Python functions — they are
templates that get inlined into the generated native code.

Available categories:
  - file I/O: open, read, write, close
  - JSON: parse, stringify
  - string: upper, lower, strip, contains, split, join
  - math: sqrt, sin, cos, tan, log, exp, floor, ceil, round

Each function maps to backend-specific runtime code emitted by the
backend's Spec or emitter.
"""
from __future__ import annotations

# File I/O runtime templates per backend
FILE_IO_RUNTIME = {
    "rust": '''
// GE File I/O runtime (Rust)
use std::io::{Read, Write};

fn ge_read_file(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_default()
}

fn ge_write_file(path: &str, content: &str) -> bool {
    std::fs::write(path, content).is_ok()
}

fn ge_append_file(path: &str, content: &str) -> bool {
    use std::io::Write;
    let mut f = std::fs::OpenOptions::new()
        .append(true)
        .create(true)
        .open(path);
    match f {
        Ok(mut f) => f.write_all(content.as_bytes()).is_ok(),
        Err(_) => false,
    }
}
''',
    "cpp": '''
// GE File I/O runtime (C++)
#include <fstream>
#include <sstream>

std::string ge_read_file(const std::string& path) {
    std::ifstream f(path);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

bool ge_write_file(const std::string& path, const std::string& content) {
    std::ofstream f(path);
    if (!f) return false;
    f << content;
    return true;
}

bool ge_append_file(const std::string& path, const std::string& content) {
    std::ofstream f(path, std::ios::app);
    if (!f) return false;
    f << content;
    return true;
}
''',
    "csharp": '''
// GE File I/O runtime (C#)
static string GeReadFile(string path) {
    return System.IO.File.ReadAllText(path);
}

static bool GeWriteFile(string path, string content) {
    try { System.IO.File.WriteAllText(path, content); return true; }
    catch { return false; }
}

static bool GeAppendFile(string path, string content) {
    try { System.IO.File.AppendAllText(path, content); return true; }
    catch { return false; }
}
''',
    "go": '''
// GE File I/O runtime (Go)
func geReadFile(path string) string {
    data, err := os.ReadFile(path)
    if err != nil { return "" }
    return string(data)
}

func geWriteFile(path string, content string) bool {
    return os.WriteFile(path, []byte(content), 0644) == nil
}

func geAppendFile(path string, content string) bool {
    f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
    if err != nil { return false }
    defer f.Close()
    _, err = f.WriteString(content)
    return err == nil
}
''',
    "kotlin": '''
// GE File I/O runtime (Kotlin) — file I/O requires JDK
// geReadFile/geWriteFile/geAppendFile omitted (JDK not in default classpath)
''',
    "zig": '''
// GE File I/O runtime (Zig)
fn ge_read_file(path: []const u8) []const u8 {
    const file = std.fs.cwd().openFile(path, .{}) catch return "";
    defer file.close();
    const stat = file.stat() catch return "";
    const buf = std.heap.page_allocator.alloc(u8, stat.size) catch return "";
    _ = file.read(buf) catch return "";
    return buf;
}

fn ge_write_file(path: []const u8, content: []const u8) bool {
    const file = std.fs.cwd.createFile(path, .{}) catch return false;
    defer file.close();
    _ = file.write(content) catch return false;
    return true;
}

fn ge_append_file(path: []const u8, content: []const u8) bool {
    const file = std.fs.cwd.openFile(path, .{ .mode = .write_only }) catch {
        const f2 = std.fs.cwd.createFile(path, .{}) catch return false;
        defer f2.close();
        _ = f2.write(content) catch return false;
        return true;
    };
    defer file.close();
    file.seekFromEnd(0) catch return false;
    _ = file.write(content) catch return false;
    return true;
}
''',
}

# Math runtime templates per backend
MATH_RUNTIME = {
    "rust": '''
// GE Math runtime (Rust)
fn ge_sqrt(x: f64) -> f64 { x.sqrt() }
fn ge_floor(x: f64) -> f64 { x.floor() }
fn ge_ceil(x: f64) -> f64 { x.ceil() }
fn ge_round(x: f64) -> f64 { x.round() }
fn ge_sin(x: f64) -> f64 { x.sin() }
fn ge_cos(x: f64) -> f64 { x.cos() }
fn ge_tan(x: f64) -> f64 { x.tan() }
fn ge_log(x: f64) -> f64 { x.ln() }
fn ge_exp(x: f64) -> f64 { x.exp() }
''',
    "cpp": '''
// GE Math runtime (C++)
std::string geStrUpper(std::string s) {
    for (auto& c : s) c = (char)std::toupper((unsigned char)c);
    return s;
}

std::string geStrLower(std::string s) {
    for (auto& c : s) c = (char)std::tolower((unsigned char)c);
    return s;
}

std::string geStrReplace(std::string s, const std::string& from,
                         const std::string& to) {
    if (from.empty()) return s;
    size_t pos = 0;
    while ((pos = s.find(from, pos)) != std::string::npos) {
        s.replace(pos, from.size(), to);
        pos += to.size();
    }
    return s;
}

std::vector<std::string> geStrSplit(const std::string& s, const std::string& sep) {
    std::vector<std::string> out;
    if (sep.empty()) { out.push_back(s); return out; }
    size_t pos = 0, found;
    while ((found = s.find(sep, pos)) != std::string::npos) {
        out.push_back(s.substr(pos, found - pos));
        pos = found + sep.size();
    }
    out.push_back(s.substr(pos));
    return out;
}

std::string geStrJoin(const std::vector<std::string>& v, const std::string& sep) {
    std::string out;
    for (size_t i = 0; i < v.size(); ++i) {
        if (i) out += sep;
        out += v[i];
    }
    return out;
}

std::vector<std::string> geDictKeys(const std::map<std::string, int64_t>& d) {
    std::vector<std::string> ks;
    ks.reserve(d.size());
    for (const auto& kv : d) ks.push_back(kv.first);
    return ks;
}

std::string geListStr(const std::vector<int64_t>& v) {
    std::string s = "[";
    for (size_t i = 0; i < v.size(); ++i) {
        if (i) s += ", ";
        s += std::to_string(v[i]);
    }
    return s + "]";
}

double ge_sqrt(double x) { return std::sqrt(x); }
double ge_floor(double x) { return std::floor(x); }
double ge_ceil(double x) { return std::ceil(x); }
double ge_round(double x) { return std::round(x); }
double ge_sin(double x) { return std::sin(x); }
double ge_cos(double x) { return std::cos(x); }
double ge_tan(double x) { return std::tan(x); }
double ge_log(double x) { return std::log(x); }
double ge_exp(double x) { return std::exp(x); }
''',
    "csharp": '''
// GE Math runtime (C#)
static double GeSqrt(double x) { return System.Math.Sqrt(x); }
static double GeFloor(double x) { return System.Math.Floor(x); }
static double GeCeil(double x) { return System.Math.Ceiling(x); }
static double GeRound(double x) { return System.Math.Round(x); }
static double GeSin(double x) { return System.Math.Sin(x); }
static double GeCos(double x) { return System.Math.Cos(x); }
static double GeTan(double x) { return System.Math.Tan(x); }
static double GeLog(double x) { return System.Math.Log(x); }
static double GeExp(double x) { return System.Math.Exp(x); }
''',
    "go": '''
// GE Math runtime (Go)
func geAbsInt(x int64) int64 {
	if x < 0 {
		return -x
	}
	return x
}

func geMin2(a, b int64) int64 {
	if a < b {
		return a
	}
	return b
}

func geMax2(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}

func geListStr(v []int64) string {
	parts := make([]string, len(v))
	for i, x := range v {
		parts[i] = strconv.FormatInt(x, 10)
	}
	return "[" + strings.Join(parts, ", ") + "]"
}

func geBoolStr(b bool) string {
	if b {
		return "True"
	}
	return "False"
}

func geSqrt(x float64) float64 { return math.Sqrt(x) }
func geFloor(x float64) float64 { return math.Floor(x) }
func geCeil(x float64) float64 { return math.Ceil(x) }
func geRound(x float64) float64 { return math.Round(x) }
func geSin(x float64) float64 { return math.Sin(x) }
func geCos(x float64) float64 { return math.Cos(x) }
func geTan(x float64) float64 { return math.Tan(x) }
func geLog(x float64) float64 { return math.Log(x) }
func geExp(x float64) float64 { return math.Exp(x) }
''',
    "kotlin": '''
// GE Math runtime (Kotlin)
import kotlin.math.*
fun ge_sqrt(x: Double): Double = sqrt(x)
fun ge_floor(x: Double): Double = floor(x)
fun ge_ceil(x: Double): Double = ceil(x)
fun ge_round(x: Double): Double = round(x)
fun ge_sin(x: Double): Double = sin(x)
fun ge_cos(x: Double): Double = cos(x)
fun ge_tan(x: Double): Double = tan(x)
fun ge_log(x: Double): Double = ln(x)
fun ge_exp(x: Double): Double = exp(x)
''',
    "zig": '''
// GE runtime (Zig)
//
// GE lists are growable, so they need an allocator. A generated program
// runs start-to-finish, so a single arena is the right fit: it amortises
// the page-grain cost across many small lists and everything is released
// in one call. (std.heap.page_allocator alone would issue a syscall per
// allocation, and GeneralPurposeAllocator is a debugging allocator.)
var ge_arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
const ge_alloc = ge_arena.allocator();

fn geListNew(comptime T: type) std.ArrayList(T) {
    return std.ArrayList(T).init(ge_alloc);
}

fn geListFrom(comptime T: type, items: []const T) std.ArrayList(T) {
    var l = std.ArrayList(T).init(ge_alloc);
    l.appendSlice(items) catch unreachable;
    return l;
}

fn geListCopy(comptime T: type, src: []const T) std.ArrayList(T) {
    return geListFrom(T, src);
}

fn geListSlice(comptime T: type, src: []const T, lo: usize, hi: usize) std.ArrayList(T) {
    var l = std.ArrayList(T).init(ge_alloc);
    l.appendSlice(src[lo..hi]) catch unreachable;
    return l;
}

fn geListConcat(comptime T: type, a: []const T, b: []const T) std.ArrayList(T) {
    var l = std.ArrayList(T).init(ge_alloc);
    l.appendSlice(a) catch unreachable;
    l.appendSlice(b) catch unreachable;
    return l;
}

// Python renders a sequence as [1, 2, 3] and quotes strings with '.
fn gePrintList(v: anytype) void {
    const w = std.io.getStdOut().writer();
    w.print("[", .{}) catch unreachable;
    for (v, 0..) |x, i| {
        if (i > 0) w.print(", ", .{}) catch unreachable;
        switch (@typeInfo(@TypeOf(x))) {
            .pointer => w.print("'{s}'", .{x}) catch unreachable,
            .float => w.print("{d}", .{x}) catch unreachable,
            .bool => w.print("{s}", .{if (x) "True" else "False"}) catch unreachable,
            else => w.print("{d}", .{x}) catch unreachable,
        }
    }
    w.print("]\\n", .{}) catch unreachable;
}

fn geSetNew(comptime T: type) std.AutoHashMap(T, void) {
    return std.AutoHashMap(T, void).init(ge_alloc);
}

fn geSetFrom(comptime T: type, items: []const T) std.AutoHashMap(T, void) {
    var s = std.AutoHashMap(T, void).init(ge_alloc);
    for (items) |x| s.put(x, {{}}) catch unreachable;
    return s;
}
fn geStrSplit(s: []const u8, sep: []const u8) std.ArrayList([]const u8) {
    var l = std.ArrayList([]const u8).init(ge_alloc);
    if (sep.len == 0) {
        l.append(s) catch unreachable;
        return l;
    }
    var it = std.mem.splitSequence(u8, s, sep);
    while (it.next()) |part| l.append(part) catch unreachable;
    return l;
}

fn geStrJoin(parts: []const []const u8, sep: []const u8) []const u8 {
    var total: usize = 0;
    for (parts, 0..) |p, i| {
        total += p.len;
        if (i > 0) total += sep.len;
    }
    const buf = ge_alloc.alloc(u8, total) catch unreachable;
    var pos: usize = 0;
    for (parts, 0..) |p, i| {
        if (i > 0) {
            @memcpy(buf[pos..][0..sep.len], sep);
            pos += sep.len;
        }
        @memcpy(buf[pos..][0..p.len], p);
        pos += p.len;
    }
    return buf;
}

fn geStrReplace(s: []const u8, from: []const u8, to: []const u8) []const u8 {
    if (from.len == 0) return s;
    var out = std.ArrayList(u8).init(ge_alloc);
    var i: usize = 0;
    while (i < s.len) {
        if (i + from.len <= s.len and std.mem.eql(u8, s[i..][0..from.len], from)) {
            out.appendSlice(to) catch unreachable;
            i += from.len;
        } else {
            out.append(s[i]) catch unreachable;
            i += 1;
        }
    }
    return out.items;
}

fn geStrUpper(s: []const u8) []const u8 {
    const buf = ge_alloc.alloc(u8, s.len) catch unreachable;
    for (s, 0..) |c, i| buf[i] = std.ascii.toUpper(c);
    return buf;
}

fn geStrLower(s: []const u8) []const u8 {
    const buf = ge_alloc.alloc(u8, s.len) catch unreachable;
    for (s, 0..) |c, i| buf[i] = std.ascii.toLower(c);
    return buf;
}
fn ge_sqrt(x: f64) f64 { return @sqrt(x); }
fn ge_floor(x: f64) f64 { return @floor(x); }
fn ge_ceil(x: f64) f64 { return @ceil(x); }
fn ge_round(x: f64) f64 { return @round(x); }
fn ge_sin(x: f64) f64 { return std.math.sin(x); }
fn ge_cos(x: f64) f64 { return std.math.cos(x); }
fn ge_tan(x: f64) f64 { return std.math.tan(x); }
fn ge_log(x: f64) f64 { return @log(x); }
fn ge_exp(x: f64) f64 { return @exp(x); }
''',
}


def get_runtime(backend: str, include_math: bool = True) -> str:
    """Get the standard library runtime code for a backend.

    Args:
        backend: one of rust, cpp, csharp, zig, go, kotlin
        include_math: whether to include math functions

    Returns:
        Backend-specific runtime code as a string.
    """
    parts = []
    if backend in FILE_IO_RUNTIME:
        parts.append(FILE_IO_RUNTIME[backend])
    if include_math and backend in MATH_RUNTIME:
        parts.append(MATH_RUNTIME[backend])
    return "\n".join(parts)


def get_file_io_runtime(backend: str) -> str:
    """Get just the file I/O runtime for a backend."""
    return FILE_IO_RUNTIME.get(backend, "")


def get_math_runtime(backend: str) -> str:
    """Get just the math runtime for a backend."""
    return MATH_RUNTIME.get(backend, "")
