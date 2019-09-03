int analogPin1 = A0; // potentiometer wiper (middle terminal) connected to analog pin 3
                    // outside leads to ground and +5V
int analogPin2 = A1; // potentiometer wiper (middle terminal) connected to analog pin 3
                    // outside leads to ground and +5V
int analogRef = A7;
int val1=0 ;  // variable to store the value read
int val2=0 ;  // variable to store the value read
int ref=0 ;
float reader=0.0; // variable to store number of samples 
float storageV1=0.0; // variable to store sum of samples 
float storageV2=0.0; // variable to store sum of samples 
float storageR=0.0;
void setup() {
  
  // put your setup code here, to run once:
  Serial.begin(9600);           //  setup serial
  analogReference(DEFAULT);
}

void loop() {
  // put your main code here, to run repeatedly:
  while(reader<190){
      val1 = analogRead(analogPin1);  // read the input pin
      val1 = analogRead(analogPin1);  // read the input pin
      //Serial.println(val1);
      val2 = analogRead(analogPin2);  // read the input pin
      val2 = analogRead(analogPin2);  // read the input pin
      //Serial.println(val2);
      ref = analogRead(analogRef);
      ref = analogRead(analogRef);
      storageV1+=(val1);
      storageV2+=(val2);
      storageR+=(ref);
      reader+=1.0;
      delay(1);
  }
  storageV1 = storageV1/reader;
  storageV2 = storageV2/reader;
  storageR = storageR/reader;

  storageV1 = storageV1/storageR*3.372;
  storageV2 = storageV2/storageR*3.372;

  //Serial.println(storageV1);
  //Serial.println(storageV2);
  Serial.print(82.7226*storageV1+1.5002379*log(233.034652422*storageV1+1)+1.2749,3); // debug value
  Serial.print("  ");
  Serial.println(82.7226*storageV2+1.5002379*log(233.034652422*storageV2+1)+1.2749,3); // debug value
  storageV1=0.0;
  storageV2=0.0;
  storageR=0.0;
  reader=0.0;
}
