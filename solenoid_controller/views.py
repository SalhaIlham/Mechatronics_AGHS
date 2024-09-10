from django.shortcuts import render, redirect
from django.contrib import messages
from datetime import datetime, timedelta
import lgpio
import time
import spidev
import requests

relay_pins = [20, 21, 19, 26]
h = lgpio.gpiochip_open(0)
spi = spidev.SpiDev()
spi.open(0, 0)  
spi.max_speed_hz = 1350000

def setup_pins():
    for pin in relay_pins:
        lgpio.gpio_free(h, pin)
    for pin in relay_pins:
        lgpio.gpio_claim_output(h, pin)

setup_pins()

def control_form(request):
    print("Rendering control_form")
    location = request.session.get('location')
    if location is None:
        return render(request, 'solenoid_controller/settings_form.html')
    else:
        return render(request, 'solenoid_controller/control_form.html')

def submit_settings(request):
    if request.method == 'POST':
        vegetable = request.POST.get('vegetables')
        postcode = request.POST.get('postcode')
        summer_start_date = request.POST.get('summer_start_date')
        summer_end_date = request.POST.get('summer_end_date')
        summer_start_time = request.POST.get('summer_start_time')
        summer_end_time = request.POST.get('summer_end_time')
       
        # Mapping vegetable to the soil moisture upper % values
        moisture_mapping = {
            'garlic': 5, 'onion': 5, 'shallots': 5,
            'artichoke': 10, 'asparagus': 10, 'carrot': 10,
            'leek': 15, 'parsnip': 15, 'pea': 15,
        }
       
        location_id = get_location_id(postcode)  # Get location ID
        tomorrows_percentage = get_weather_data(location_id)  # Fetch the weather forecast
        store_forecast_in_session(request, tomorrows_percentage)  # Store forecast data in session

        # Calculate sensor threshold and runtime from the selected vegetable
        upper_percent = moisture_mapping.get(vegetable)
        sensor_threshold = upper_percent * 100
        runtime = upper_percent * 60  # seconds
       
        # Store sensor threshold, runtime, and seasonal settings in the session
        request.session['sensor_threshold'] = sensor_threshold
        request.session['runtime'] = runtime
        request.session['postcode'] = postcode
        request.session['summer_start_date'] = summer_start_date
        request.session['summer_end_date'] = summer_end_date
        request.session['summer_start_time'] = summer_start_time
        request.session['summer_end_time'] = summer_end_time

        # Send confirmation message to user
        messages.success(request, 'Settings have been saved.')
        return redirect('control_form')  # Go back to the control form

def submit_control(request):
    if request.method == 'POST':
        try:
            relay_num = int(request.POST.get('relay'))
            action = request.POST.get('action')
            selected_pin = relay_pins[relay_num - 1]
            
            if action == 'settings':
                return redirect('settings_form')
            elif action == 'on':
                lgpio.gpio_write(h, selected_pin, 1)
            elif action == 'off':
                lgpio.gpio_write(h, selected_pin, 0)
            elif action == 'activate':
                if is_forecast_data_outdated(request):  # Check if forecast is outdated
                    postcode = request.session.get('postcode')  # Get the postcode from the session
                    location_id = get_location_id(postcode)  # Get location ID
                    tomorrows_percentage = get_weather_data(location_id)  # Refresh forecast data
                    store_forecast_in_session(request, tomorrows_percentage)  # Store the updated forecast

                sensor_threshold = request.session.get('sensor_threshold', 2000)  # Default threshold
                run_time = request.session.get('runtime', 120)  # Default runtime in seconds
                summer_start_date = request.session.get('summer_start_date')
                summer_end_date = request.session.get('summer_end_date')
                summer_start_time = request.session.get('summer_start_time')
                summer_end_time = request.session.get('summer_end_time')
                current_date = datetime.now().strftime('%Y-%m-%d')
                current_time = datetime.now().strftime('%H:%M:%S')
                
                # Check if the current date and time fall within the summer watering window
                if is_summer(current_date, current_time, summer_start_date, summer_end_date, summer_start_time, summer_end_time):
                    while True:
                        sensor_value = read_sensor()  # Read the soil moisture sensor
                        if sensor_value < sensor_threshold:  # Check if the soil is too dry
                            tomorrows_forecast = request.session.get('tomorrows_percentage', 0)  # Fetch stored forecast %                        
                            if tomorrows_forecast < 75:  # Check if it's going to rain
                                lgpio.gpio_write(h, selected_pin, 1)  # Turn the relay on
                                startTime = time.time()  # Start the runtime
                                while time.time() < startTime + run_time:
                                    time.sleep(0.1)  # The relay remains on for the specified run time                          
                                lgpio.gpio_write(h, selected_pin, 0)  # Turn the relay off
                        # Check for system deactivation request
                        if request.POST.get('action') == 'deactivate':
                            break
            return redirect('control_form')  # Go back to the control form
        except Exception as e:
            return redirect('control_form')
    return redirect('control_form')

def read_adc(channel):
    adc = spi.xfer2([1, (8 + channel) << 4, 0])  # Perform SPI transfer
    data = ((adc[1] & 3) << 8) + adc[2]  # Convert the result to a value
    return data

def read_sensor():
    moisture_level = read_adc(0)  # Read from channel 0
    return moisture_level

def store_forecast_in_session(request, tomorrows_percentage):
    request.session['tomorrows_percentage'] = tomorrows_percentage
    request.session['forecast_timestamp'] = datetime.now().isoformat()  

def is_forecast_data_outdated(request):
    forecast_timestamp_str = request.session.get('forecast_timestamp')
    if forecast_timestamp_str:
        forecast_timestamp = datetime.fromisoformat(forecast_timestamp_str)
        if datetime.now() - forecast_timestamp > timedelta(hours=24):
            return True
    return False

def is_summer(current_date, current_time, summer_start_date, summer_end_date, summer_start_time, summer_end_time):
    summer_start = datetime.strptime(f"{summer_start_date} {summer_start_time}", '%Y-%m-%d %H:%M:%S')
    summer_end = datetime.strptime(f"{summer_end_date} {summer_end_time}", '%Y-%m-%d %H:%M:%S')
    current_datetime = datetime.strptime(f"{current_date} {current_time}", '%Y-%m-%d %H:%M:%S')
    return summer_start <= current_datetime <= summer_end

def get_weather_data(location_id):
    api_key = 'YWM2MDg5ZGQ1ZjgzZWU3NTRmYzZkOD'
    headers = {"Content-Type": "application/json"}
    tomorrow_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    forecast_url = f"https://api.willyweather.com.au/v2/{api_key}/locations/{location_id}/weather.json"
    payload = {
        "forecasts": ["rainfallprobability"],
        "days": 1,
        "startDate": tomorrow_date
    }
    try:
        response = requests.get(forecast_url, headers=headers, params=payload)
        response.raise_for_status()
        data = response.json()
        tomorrows_percentage = data['forecasts']['rainfallprobability']['days'][0]['entries'][0].get('probability', 'N/A')
        return tomorrows_percentage
    except (requests.RequestException, KeyError) as e:
        return None

def get_location_id(postcode):
    api_key = 'YWM2MDg5ZGQ1ZjgzZWU3NTRmYzZkOD'
    search_url = f"https://api.willyweather.com.au/v2/{api_key}/search.json"
    search_payload = {
        "query": postcode,
        "limit": 1
    }
    headers = {
        "Content-Type": "application/json",
    }
    try:
        search_response = requests.post(search_url, headers=headers, json=search_payload)
        search_response.raise_for_status()
        search_data = search_response.json()
        if search_data and 'locations' in search_data:
            location_info = search_data['locations'][0]
            return location_info.get('id')
    except requests.RequestException as e:
        return None
