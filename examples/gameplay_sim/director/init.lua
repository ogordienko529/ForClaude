-- Scripted world events for a simulated raw gameplay recording.
-- The recording driver writes one command per line to <world>/director_cmd.txt; this mod polls it.
local cmd_file = minetest.get_worldpath() .. "/director_cmd.txt"
local done = 0          -- number of command lines already executed
local queue = {}        -- pending {pos, node} placements for the progressive build
local build_rate = 10   -- blocks per second for the progressive build
local house = nil       -- footprint of the last house: {x0, z0, y, size}
local portal = nil      -- the last portal frame: {base = pos (bottom middle), axis = "x"|"z"}

local function player()
	return minetest.get_connected_players()[1]
end

local function ground_y(x, z, y_guess)
	for y = y_guess + 12, y_guess - 20, -1 do
		local n = minetest.get_node({x = x, y = y, z = z}).name
		local def = minetest.registered_nodes[n]
		if def and def.walkable and n ~= "air" and not n:find("leaves") and not n:find("tree") then
			return y
		end
	end
	return y_guess - 1
end

local function forward(p, dist)
	local yaw = p:get_look_horizontal()
	local pos = p:get_pos()
	return {x = math.floor(pos.x - math.sin(yaw) * dist + 0.5), z = math.floor(pos.z + math.cos(yaw) * dist + 0.5), y = math.floor(pos.y)}
end

local commands = {}
minetest.log("action", "[director] loaded, commands from " .. cmd_file)

function commands.day()
	minetest.set_timeofday(0.32)
end

function commands.give()
	local inv = player():get_inventory()
	inv:set_list("main", {})
	for _, item in ipairs({"default:pick_diamond", "default:wood 99", "default:glass 99", "default:tree 99",
			"default:cobble 99", "default:torch 99", "tnt:tnt 99", "fire:flint_and_steel"}) do
		inv:add_item("main", item)
	end
end

-- Remove trees and plants around the player so there is room to build and a clear view.
function commands.clear(radius)
	radius = tonumber(radius) or 18
	local pos = vector.round(player():get_pos())
	for x = pos.x - radius, pos.x + radius do
		for z = pos.z - radius, pos.z + radius do
			for y = pos.y - 3, pos.y + 25 do
				local p = {x = x, y = y, z = z}
				local n = minetest.get_node(p).name
				if n:find("tree") or n:find("leaves") or n:find("apple") or n:find("mushroom") then
					minetest.remove_node(p)
				end
			end
		end
	end
end

-- An obsidian Nether portal frame (4 wide, 5 high, 14 blocks) placed block by block in front of the player.
function commands.portal()
	local p = player()
	local c = forward(p, 6)
	local y = ground_y(c.x, c.z, c.y) + 1
	local yaw = p:get_look_horizontal()
	-- the frame faces the player: it runs across the look direction
	local along_x = math.abs(math.cos(yaw)) > math.abs(math.sin(yaw))
	local function at(i, h)
		if along_x then return {x = c.x - 1 + i, y = y + h, z = c.z} end
		return {x = c.x, y = y + h, z = c.z - 1 + i}
	end
	portal = {base = at(1, 0), axis = along_x and "x" or "z"}
	build_rate = 2.5
	for i = 0, 3 do table.insert(queue, {at(i, 0), {name = "default:obsidian"}}) end
	for h = 1, 4 do
		table.insert(queue, {at(0, h), {name = "default:obsidian"}})
		table.insert(queue, {at(3, h), {name = "default:obsidian"}})
	end
	for i = 1, 2 do table.insert(queue, {at(i, 4), {name = "default:obsidian"}}) end
end

-- Light the portal the way a player does: right-click the frame with a mese crystal fragment.
function commands.light()
	if not portal then return end
	local item = minetest.registered_items["default:mese_crystal_fragment"]
	local pt = {type = "node", under = portal.base, above = vector.add(portal.base, {x = 0, y = 1, z = 0})}
	item.on_place(ItemStack("default:mese_crystal_fragment"), player(), pt)
end

-- Step into the middle of the lit portal (the last metre of the walk, so the player stands inside it).
function commands.enter()
	if not portal then return end
	local p = player()
	local target = vector.add(portal.base, {x = portal.axis == "x" and 0.5 or 0, y = 1, z = portal.axis == "z" and 0.5 or 0})
	p:set_pos(target)
end

-- Light up the surroundings the way a player places torches: glowstone on nearby walls and ceiling.
function commands.glow(radius)
	radius = tonumber(radius) or 9
	local pos = vector.round(player():get_pos())
	local placed = 0
	for _ = 1, 400 do
		local q = vector.add(pos, {x = math.random(-radius, radius), y = math.random(-2, 6), z = math.random(-radius, radius)})
		local n = minetest.get_node(q).name
		if (n == "nether:rack" or n == "nether:rack_deep" or n == "nether:basalt") and
				minetest.find_node_near(q, 1, {"air"}) and vector.distance(q, pos) > 2.5 then
			minetest.set_node(q, {name = "nether:glowstone"})
			placed = placed + 1
			if placed >= 26 then break end
		end
	end
	minetest.log("action", "[director] glow placed " .. placed)
end

function commands.give_nether()
	local inv = player():get_inventory()
	inv:set_list("main", {})
	for _, item in ipairs({"default:pick_diamond", "default:obsidian 99", "default:mese_crystal_fragment 99",
			"nether:pick_nether", "nether:rack 99", "nether:glowstone 99", "default:torch 99", "nether:brick 99"}) do
		inv:add_item("main", item)
	end
end

-- Queue a small house 7 blocks in front of the player; blocks appear one by one like a fast builder.
function commands.build()
	local p = player()
	local c = forward(p, 8)
	build_rate = 10
	local size = 7
	local x0, z0 = c.x - 3, c.z - 3
	local y = ground_y(c.x, c.z, c.y)
	house = {x0 = x0, z0 = z0, y = y, size = size}
	local function add(x, yy, z, name) table.insert(queue, {{x = x, y = yy, z = z}, {name = name}}) end
	for x = x0, x0 + size - 1 do for z = z0, z0 + size - 1 do add(x, y, z, "default:cobble") end end
	for h = 1, 4 do
		for x = x0, x0 + size - 1 do
			for z = z0, z0 + size - 1 do
				local edge_x = (x == x0 or x == x0 + size - 1)
				local edge_z = (z == z0 or z == z0 + size - 1)
				if edge_x or edge_z then
					local name = "default:wood"
					if edge_x and edge_z then name = "default:tree" end
					local door = (z == z0 and x == x0 + 3 and h <= 2)
					local window = (h == 2 or h == 3) and not (edge_x and edge_z) and ((x - x0) % 3 == 1 or (z - z0) % 3 == 1)
					if door then name = nil elseif window and not (z == z0 and x == x0 + 3) then name = "default:glass" end
					if name then add(x, y + h, z, name) end
				end
			end
		end
	end
	for layer = 0, 3 do
		for x = x0 - 1 + layer, x0 + size - layer do
			for z = z0 - 1 + layer, z0 + size - layer do
				if layer == 3 or x == x0 - 1 + layer or x == x0 + size - layer or z == z0 - 1 + layer or z == z0 + size - layer then
					add(x, y + 5 + layer, z, "default:brick")
				end
			end
		end
	end
	add(x0 + 3, y + 3, z0 - 1, "default:torch_wall")
end

local TNT_SPOTS = {{3, 1, -1}, {3, 1, 3}, {1, 1, 1}, {5, 1, 5}, {1, 1, 5}, {5, 1, 1}, {3, 2, 3}, {3, 1, 1}, {3, 1, 5}}

-- TNT blocks appear inside and in front of the house ...
function commands.tnt()
	if not house then return end
	for i, off in ipairs(TNT_SPOTS) do
		minetest.after(0.12 * i, function()
			minetest.set_node({x = house.x0 + off[1], y = house.y + off[2], z = house.z0 + off[3]}, {name = "tnt:tnt"})
		end)
	end
end

-- ... and are lit (4 s fuse, then they explode).
function commands.ignite()
	if not house then return end
	for _, off in ipairs(TNT_SPOTS) do
		local pos = {x = house.x0 + off[1], y = house.y + off[2], z = house.z0 + off[3]}
		if minetest.get_node(pos).name == "tnt:tnt" then
			minetest.swap_node(pos, {name = "tnt:tnt_burning"})
			minetest.registered_nodes["tnt:tnt_burning"].on_construct(pos)
		end
	end
end

-- Log the player's position and look direction (used to calibrate the input driver).
function commands.report()
	local p = player()
	local pos = p:get_pos()
	minetest.log("action", string.format("[director] report %.2f %.2f %.2f yaw=%.1f pitch=%.1f", pos.x, pos.y, pos.z,
		math.deg(p:get_look_horizontal()), math.deg(p:get_look_vertical())))
end

-- How far to turn to look at the house centre or the portal (the input driver turns smoothly by this much).
function commands.aim(what)
	local target
	if what == "portal" or what == "portal_base" then
		if not portal then return end
		target = vector.add(portal.base, {x = portal.axis == "x" and 0.5 or 0, y = what == "portal" and 2 or 0,
			z = portal.axis == "z" and 0.5 or 0})
	else
		if not house then return end
		target = {x = house.x0 + house.size / 2 - 0.5, y = house.y + 2.5, z = house.z0 + house.size / 2 - 0.5}
	end
	local p = player()
	local eye = vector.add(p:get_pos(), {x = 0, y = 1.5, z = 0})
	local d = vector.subtract(target, eye)
	local yaw = math.atan2(-d.x, d.z)
	local pitch = -math.atan2(d.y, math.sqrt(d.x * d.x + d.z * d.z))
	local dyaw = math.deg(yaw - p:get_look_horizontal())
	dyaw = (dyaw + 180) % 360 - 180
	local dpitch = math.deg(pitch - p:get_look_vertical())
	minetest.log("action", string.format("[director] aim dyaw=%.2f dpitch=%.2f dist=%.2f", dyaw, dpitch,
		math.sqrt(d.x * d.x + d.z * d.z)))
end

local acc, build_acc = 0, 0
minetest.register_globalstep(function(dtime)
	-- progressive build: about ten blocks a second, like a fast builder
	build_acc = build_acc + dtime
	while build_acc >= 1 / build_rate do
		build_acc = build_acc - 1 / build_rate
		local item = table.remove(queue, 1)
		if not item then build_acc = 0 break end
		minetest.set_node(item[1], item[2])
	end
	acc = acc + dtime
	if acc < 0.1 then return end
	acc = 0
	local f = io.open(cmd_file, "r")
	if not f then return end
	local lines = {}
	for line in f:lines() do table.insert(lines, line) end
	f:close()
	while done < #lines do
		done = done + 1
		local words = lines[done]:split(" ")
		local fn = commands[words[1]]
		minetest.log("action", "[director] " .. lines[done])
		if fn and player() then fn(words[2], words[3]) end
	end
end)
